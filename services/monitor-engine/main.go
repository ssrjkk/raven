package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	_ "modernc.org/sqlite"
	"github.com/nats-io/nats.go/jetstream"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/cors"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

type contextKey string

const contextReqID contextKey = "req_id"

type MonitorEngine struct {
	db          *sql.DB
	nc          *nats.Conn
	js          jetstream.JetStream
	logger      *slog.Logger
	started     time.Time
	workerCount int32
	rootCtx     context.Context
	rootCancel  context.CancelFunc

	checkDuration     prometheus.Histogram
	checkErrors       prometheus.Counter
	activeChecks      prometheus.Gauge
	httpRequests      *prometheus.CounterVec
	checkLastDuration prometheus.Gauge

	checks   map[string]*Monitor
	checksMu sync.RWMutex
	cancelMu sync.Mutex
	cancels  map[string]context.CancelFunc
}

type Monitor struct {
	ID             string  `json:"id"`
	Name           string  `json:"name"`
	URL            string  `json:"url"`
	IntervalSec    int     `json:"interval_seconds"`
	TimeoutSec     int     `json:"timeout_seconds"`
	LastStatus     string  `json:"last_status"`
	LastDurationMs float64 `json:"last_duration_ms"`
	Enabled        bool    `json:"enabled"`
}

type ErrorResponse struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}

func NewMonitorEngine() *MonitorEngine {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	ctx, cancel := context.WithCancel(context.Background())
	return &MonitorEngine{
		logger:  logger,
		started: time.Now(),
		rootCtx: ctx,
		rootCancel: cancel,
		checks:  make(map[string]*Monitor),
		cancels: make(map[string]context.CancelFunc),
		checkDuration: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name: "monitor_check_duration_seconds", Help: "Check duration",
			Buckets: prometheus.DefBuckets,
		}),
		checkErrors: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "monitor_check_errors_total", Help: "Check errors",
		}),
		activeChecks: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "monitor_active_checks", Help: "Active checks",
		}),
		checkLastDuration: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "monitor_last_check_duration_ms", Help: "Last check duration",
		}),
		httpRequests: prometheus.NewCounterVec(
			prometheus.CounterOpts{Name: "monitor_http_requests_total", Help: "HTTP requests"},
			[]string{"method", "path", "status"},
		),
	}
}

func (m *MonitorEngine) InitDB(path string) error {
	var err error
	m.db, err = sql.Open("sqlite", path+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		return fmt.Errorf("sqlite: %w", err)
	}
	m.db.SetMaxOpenConns(1)
	m.db.SetConnMaxLifetime(5 * time.Minute)
	_, err = m.db.Exec(`CREATE TABLE IF NOT EXISTS monitors (
		id TEXT PRIMARY KEY, name TEXT, url TEXT, interval_sec INTEGER DEFAULT 60,
		timeout_sec INTEGER DEFAULT 10, enabled INTEGER DEFAULT 1,
		last_status TEXT DEFAULT 'unknown', last_duration_ms REAL DEFAULT 0,
		created_at TEXT DEFAULT (datetime('now'))
	)`)
	if err != nil {
		return err
	}
	for _, idx := range []string{
		"CREATE INDEX IF NOT EXISTS idx_monitors_created ON monitors(created_at)",
		"CREATE INDEX IF NOT EXISTS idx_monitors_status ON monitors(last_status)",
	} {
		if _, err := m.db.Exec(idx); err != nil {
			m.logger.Warn("index creation failed", "error", err)
		}
	}

	go m.cleanupOldMonitors(24 * time.Hour)
	return nil
}

func (m *MonitorEngine) cleanupOldMonitors(ttl time.Duration) {
	ticker := time.NewTicker(1 * time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			cutoff := time.Now().Add(-ttl).Format("2006-01-02 15:04:05")
			res, err := m.db.ExecContext(m.rootCtx, "DELETE FROM monitors WHERE created_at < ?", cutoff)
			if err != nil {
				m.logger.Warn("cleanup error", "error", err)
				continue
			}
			if n, _ := res.RowsAffected(); n > 0 {
				m.logger.Info("cleaned old monitors", "count", n)
			}
		case <-m.rootCtx.Done():
			return
		}
	}
}

func (m *MonitorEngine) InitNATS(url string) error {
	nc, err := nats.Connect(url, nats.Name("monitor-engine"))
	if err != nil {
		return err
	}
	m.nc = nc
	js, err := jetstream.New(nc)
	if err != nil {
		return err
	}
	m.js = js
	return nil
}

func (m *MonitorEngine) InitOTel(endpoint string) (*sdktrace.TracerProvider, error) {
	exporter, err := otlptracegrpc.New(context.Background(),
		otlptracegrpc.WithEndpoint(endpoint), otlptracegrpc.WithInsecure())
	if err != nil {
		return nil, err
	}
	res := resource.NewWithAttributes(semconv.SchemaURL,
		semconv.ServiceNameKey.String("monitor-engine"),
		semconv.ServiceVersionKey.String("1.0.0"),
	)
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{}, propagation.Baggage{}))
	return tp, nil
}

func (m *MonitorEngine) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "healthy", "service": "monitor-engine",
			"active_checks": len(m.checks), "uptime": time.Since(m.started).String(),
		})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if m.db == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]string{"status": "not ready"})
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	mux.Handle("GET /metrics", promhttp.Handler())

	mux.HandleFunc("GET /api/v1/monitors", m.listMonitors)
	mux.HandleFunc("POST /api/v1/monitors", m.createMonitor)
	mux.HandleFunc("DELETE /api/v1/monitors/{id}", m.deleteMonitor)

	return otelhttp.NewHandler(m.metricsMiddleware(m.requestIDMiddleware(m.loggingMiddleware(m.authMiddleware(mux)))), "monitor-engine")
}

func (m *MonitorEngine) authMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" || len(authHeader) < 7 || authHeader[:7] != "Bearer " {
			writeMonitorError(w, http.StatusUnauthorized, "missing or invalid token")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (m *MonitorEngine) requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			id = uuid.New().String()[:8]
		}
		w.Header().Set("X-Request-ID", id)
		ctx := context.WithValue(r.Context(), contextReqID, id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (m *MonitorEngine) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		reqID, _ := r.Context().Value(contextReqID).(string)
		next.ServeHTTP(sw, r)
		m.logger.Info("request",
			"method", r.Method, "path", r.URL.Path,
			"status", sw.status, "duration_ms", time.Since(start).Milliseconds(),
			"req_id", reqID,
		)
	})
}

func (m *MonitorEngine) metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		m.httpRequests.WithLabelValues(r.Method, r.URL.Path, fmt.Sprint(sw.status)).Inc()
		m.checkDuration.Observe(time.Since(start).Seconds())
	})
}

func writeMonitorError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(ErrorResponse{Error: msg})
}

func (m *MonitorEngine) listMonitors(w http.ResponseWriter, r *http.Request) {
	m.checksMu.RLock()
	items := make([]*Monitor, 0, len(m.checks))
	for _, ch := range m.checks {
		items = append(items, ch)
	}
	m.checksMu.RUnlock()
	writeJSON(w, http.StatusOK, map[string]interface{}{"monitors": items})
}

func (m *MonitorEngine) createMonitor(w http.ResponseWriter, r *http.Request) {
	var mon Monitor
	if err := json.NewDecoder(r.Body).Decode(&mon); err != nil {
		writeMonitorError(w, http.StatusBadRequest, "invalid body")
		return
	}
	mon.ID = uuid.New().String()
	if mon.IntervalSec < 10 {
		mon.IntervalSec = 60
	}
	if mon.TimeoutSec < 1 {
		mon.TimeoutSec = 10
	}
	mon.Enabled = true
	mon.LastStatus = "pending"

	monPtr := &mon

	m.checksMu.Lock()
	m.checks[mon.ID] = monPtr
	m.checksMu.Unlock()

	if m.db != nil {
		if _, err := m.db.ExecContext(r.Context(),
			"INSERT INTO monitors (id, name, url, interval_sec, timeout_sec) VALUES (?, ?, ?, ?, ?)",
			mon.ID, mon.Name, mon.URL, mon.IntervalSec, mon.TimeoutSec); err != nil {
			m.logger.Error("db insert failed", "monitor_id", mon.ID, "error", err)
		}
	}

	monCtx, monCancel := context.WithCancel(m.rootCtx)
	m.cancelMu.Lock()
	m.cancels[mon.ID] = monCancel
	m.cancelMu.Unlock()
	go m.runCheck(monCtx, monPtr)

	w.WriteHeader(http.StatusCreated)
	writeJSON(w, http.StatusCreated, mon)
}

func (m *MonitorEngine) deleteMonitor(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		parts := strings.Split(r.URL.Path, "/")
		if len(parts) > 0 {
			id = parts[len(parts)-1]
		}
	}
	if id == "" {
		writeMonitorError(w, http.StatusBadRequest, "missing id")
		return
	}
	m.checksMu.Lock()
	delete(m.checks, id)
	m.checksMu.Unlock()

	m.cancelMu.Lock()
	if cancel, ok := m.cancels[id]; ok {
		cancel()
		delete(m.cancels, id)
	}
	m.cancelMu.Unlock()

	if m.db != nil {
		if _, err := m.db.ExecContext(r.Context(), "DELETE FROM monitors WHERE id = ?", id); err != nil {
			m.logger.Error("db delete failed", "monitor_id", id, "error", err)
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

func (m *MonitorEngine) runCheck(ctx context.Context, mon *Monitor) {
	client := &http.Client{Timeout: time.Duration(mon.TimeoutSec) * time.Second}

	for {
		select {
		case <-ctx.Done():
			m.logger.Info("monitor check stopped", "monitor_id", mon.ID)
			return
		default:
		}

		if !mon.Enabled {
			time.Sleep(time.Duration(mon.IntervalSec) * time.Second)
			continue
		}

		m.activeChecks.Inc()
		start := time.Now()

		checkCtx, checkCancel := context.WithTimeout(ctx, time.Duration(mon.TimeoutSec)*time.Second)
		req, _ := http.NewRequestWithContext(checkCtx, "GET", mon.URL, nil)
		resp, err := client.Do(req)
		checkCancel()
		duration := time.Since(start)

		mon.LastDurationMs = float64(duration.Milliseconds())
		m.checkDuration.Observe(duration.Seconds())
		m.checkLastDuration.Set(mon.LastDurationMs)

		if err != nil {
			mon.LastStatus = "error"
			m.checkErrors.Inc()
			m.logger.Warn("check failed", "monitor_id", mon.ID, "url", mon.URL, "error", err)
		} else {
			resp.Body.Close()
			if resp.StatusCode >= 200 && resp.StatusCode < 400 {
				mon.LastStatus = "up"
			} else {
				mon.LastStatus = fmt.Sprintf("down_%d", resp.StatusCode)
				m.checkErrors.Inc()
			}
		}

		if m.js != nil && m.nc.IsConnected() {
			result, _ := json.Marshal(map[string]interface{}{
				"monitor_id": mon.ID, "status": mon.LastStatus,
				"duration_ms": mon.LastDurationMs, "timestamp": time.Now().Unix(),
			})
			if _, err := m.js.Publish(ctx, "monitor.check.completed", result); err != nil {
				m.logger.Warn("nats publish failed", "monitor_id", mon.ID, "error", err)
			}
		}

		m.activeChecks.Dec()

		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Duration(mon.IntervalSec) * time.Second):
		}
	}
}

func (m *MonitorEngine) loadChecks() {
	if m.db == nil {
		return
	}
	rows, err := m.db.QueryContext(m.rootCtx, "SELECT id, name, url, interval_sec, timeout_sec, last_status, last_duration_ms, enabled FROM monitors WHERE enabled = 1")
	if err != nil {
		m.logger.Warn("load checks query failed", "error", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var mon Monitor
		var enabledInt int
		if err := rows.Scan(&mon.ID, &mon.Name, &mon.URL, &mon.IntervalSec, &mon.TimeoutSec, &mon.LastStatus, &mon.LastDurationMs, &enabledInt); err != nil {
			m.logger.Error("row scan failed", "error", err)
			continue
		}
		mon.Enabled = enabledInt == 1
		monPtr := &mon
		m.checksMu.Lock()
		m.checks[mon.ID] = monPtr
		m.checksMu.Unlock()

		monCtx, monCancel := context.WithCancel(m.rootCtx)
		m.cancelMu.Lock()
		m.cancels[mon.ID] = monCancel
		m.cancelMu.Unlock()
		go m.runCheck(monCtx, monPtr)
	}
	if err := rows.Err(); err != nil {
		m.logger.Error("rows iteration failed", "error", err)
	}
	m.logger.Info("loaded monitors", "count", len(m.checks))
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (m *MonitorEngine) Shutdown() {
	m.logger.Info("shutting down monitor engine")
	m.rootCancel()
}

func main() {
	svc := NewMonitorEngine()

	if err := svc.InitDB(envOr("DB_PATH", "/data/monitor.db")); err != nil {
		svc.logger.Warn("db unavailable", "error", err)
	}
	if err := svc.InitNATS(envOr("NATS_URL", "nats://nats:4222")); err != nil {
		svc.logger.Warn("NATS unavailable", "error", err)
	}
	if tp, err := svc.InitOTel(envOr("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")); err == nil {
		defer tp.Shutdown(context.Background())
	}

	svc.loadChecks()

	port := envOr("SERVICE_PORT", "8003")
	allowedOrigins := envOr("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")

	handler := svc.Routes()
	if origins := splitCSV(allowedOrigins); len(origins) > 0 {
		handler = cors.New(cors.Options{
			AllowedOrigins:   origins,
			AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
			AllowedHeaders:   []string{"Authorization", "Content-Type", "X-Request-ID"},
			AllowCredentials: true,
			MaxAge:           300,
		}).Handler(handler)
	}

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      handler,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		svc.logger.Info("monitor-engine starting", "port", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			svc.logger.Error("server error", "error", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	svc.Shutdown()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	server.Shutdown(ctx)
	if svc.nc != nil {
		svc.nc.Close()
	}
	if svc.db != nil {
		svc.db.Close()
	}
	wg.Wait()
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func splitCSV(s string) []string {
	if s == "" {
		return nil
	}
	var result []string
	start := 0
	for i := 0; i <= len(s); i++ {
		if i == len(s) || s[i] == ',' {
			if i > start {
				result = append(result, s[start:i])
			}
			start = i + 1
		}
	}
	return result
}
