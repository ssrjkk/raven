package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
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

const (
	contextUserID contextKey = "user_id"
	contextRole   contextKey = "role"
	contextReqID  contextKey = "req_id"
)

type Gateway struct {
	nc         *nats.Conn
	js         jetstream.JetStream
	logger     *slog.Logger
	started    time.Time
	authClient *AuthClient
	authCB     *CircuitBreaker
	rateLimiter *RateLimiter

	httpRequests *prometheus.CounterVec
	httpDuration *prometheus.HistogramVec
}

func NewGateway() *Gateway {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))

	g := &Gateway{
		logger:  logger,
		started: time.Now(),
		httpRequests: prometheus.NewCounterVec(
			prometheus.CounterOpts{Name: "http_requests_total", Help: "Total HTTP requests"},
			[]string{"method", "path", "status"},
		),
		httpDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{Name: "http_request_duration_seconds", Help: "Request duration",
				Buckets: prometheus.DefBuckets},
			[]string{"method", "path"},
		),
	}
	prometheus.MustRegister(g.httpRequests, g.httpDuration)
	return g
}

func (g *Gateway) InitNATS(url string) error {
	nc, err := nats.Connect(url, nats.Name("gateway"))
	if err != nil {
		return fmt.Errorf("nats connect: %w", err)
	}
	g.nc = nc
	js, err := jetstream.New(nc)
	if err != nil {
		return fmt.Errorf("jetstream: %w", err)
	}
	g.js = js
	g.logger.Info("connected to NATS", "url", url)
	return nil
}

func (g *Gateway) InitOTel(endpoint string) (*sdktrace.TracerProvider, error) {
	ctx := context.Background()
	exporter, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure())
	if err != nil {
		return nil, fmt.Errorf("otel exporter: %w", err)
	}
	res := resource.NewWithAttributes(semconv.SchemaURL,
		semconv.ServiceNameKey.String("gateway"),
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

func (g *Gateway) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":  "healthy",
			"service": "gateway",
			"uptime":  time.Since(g.started).String(),
		})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if g.nc == nil || !g.nc.IsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]string{"status": "not ready", "reason": "NATS disconnected"})
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	mux.Handle("GET /metrics", promhttp.Handler())

	mux.HandleFunc("POST /api/v1/auth/register", g.proxyTo("http://auth:8001"))
	mux.HandleFunc("POST /api/v1/auth/login", g.proxyTo("http://auth:8001"))
	mux.HandleFunc("POST /api/v1/auth/validate", g.proxyTo("http://auth:8001"))

	mux.Handle("GET /api/v1/monitors", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://monitor-engine:8003"))))
	mux.Handle("POST /api/v1/monitors", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://monitor-engine:8003"))))
	mux.Handle("DELETE /api/v1/monitors/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://monitor-engine:8003"))))
	mux.Handle("GET /api/v1/rag/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://rag-service:8004"))))
	mux.Handle("POST /api/v1/rag/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://rag-service:8004"))))
	mux.Handle("/api/v1/tasks/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://task-engine:8005"))))
	mux.Handle("POST /api/v1/code/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://code-service:8006"))))
	mux.Handle("/api/v1/agent/", g.authMiddleware(http.HandlerFunc(g.proxyTo("http://agent-core:8002"))))

	rateLimited := g.rateLimitMiddleware(g.metricsMiddleware(g.requestIDMiddleware(g.loggingMiddleware(mux))))
	return otelhttp.NewHandler(rateLimited, "gateway")
}

func (g *Gateway) authMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if g.authClient == nil {
			writeError(w, http.StatusBadGateway, ErrAuthUnavailable, "auth unavailable")
			return
		}
		if g.authCB != nil && !g.authCB.Allow() {
			writeError(w, http.StatusBadGateway, ErrAuthUnavailable, "auth circuit open")
			return
		}
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" || len(authHeader) < 7 || authHeader[:7] != "Bearer " {
			writeError(w, http.StatusUnauthorized, ErrUnauthorized, "missing or invalid authorization header")
			return
		}
		token := authHeader[7:]
		userID, role, err := g.authClient.ValidateToken(r.Context(), token)
		if err != nil {
			if g.authCB != nil {
				g.authCB.Failure()
			}
			writeError(w, http.StatusUnauthorized, ErrUnauthorized, "invalid or expired token")
			return
		}
		if g.authCB != nil {
			g.authCB.Success()
		}
		ctx := context.WithValue(r.Context(), contextUserID, userID)
		ctx = context.WithValue(ctx, contextRole, role)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (g *Gateway) requestIDMiddleware(next http.Handler) http.Handler {
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

func (g *Gateway) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		reqID, _ := r.Context().Value(contextReqID).(string)
		next.ServeHTTP(sw, r)
		g.logger.Info("request",
			"method", r.Method, "path", r.URL.Path,
			"status", sw.status, "duration_ms", time.Since(start).Milliseconds(),
			"req_id", reqID, "remote", r.RemoteAddr,
		)
	})
}

func (g *Gateway) metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sw := &statusWriter{ResponseWriter: w, status: 200}
		start := time.Now()
		next.ServeHTTP(sw, r)
		g.httpRequests.WithLabelValues(r.Method, r.URL.Path, fmt.Sprint(sw.status)).Inc()
		g.httpDuration.WithLabelValues(r.Method, r.URL.Path).Observe(time.Since(start).Seconds())
	})
}

func (g *Gateway) proxyTo(base string) http.HandlerFunc {
	client := &http.Client{Timeout: 30 * time.Second}
	return func(w http.ResponseWriter, r *http.Request) {
		target := base + r.URL.Path
		if r.URL.RawQuery != "" {
			target += "?" + r.URL.RawQuery
		}

		ctx := r.Context()
		if _, ok := ctx.Deadline(); !ok {
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, 25*time.Second)
			defer cancel()
		}

		body := r.Body
		if r.Body != nil {
			defer r.Body.Close()
		}

		req, err := http.NewRequestWithContext(ctx, r.Method, target, body)
		if err != nil {
			writeError(w, http.StatusBadGateway, ErrUpstream, "invalid upstream request")
			return
		}
		req.Header = r.Header.Clone()

		resp, err := client.Do(req)
		if err != nil {
			g.logger.Error("proxy error", "target", target, "error", err)
			writeError(w, http.StatusBadGateway, ErrUpstream, "upstream unreachable")
			return
		}
		defer resp.Body.Close()

		for k, v := range resp.Header {
			w.Header()[k] = v
		}
		w.WriteHeader(resp.StatusCode)
		if _, err := io.Copy(w, resp.Body); err != nil {
			g.logger.Error("proxy copy error", "target", target, "error", err)
		}
	}
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	gateway := NewGateway()

	natsURL := envOr("NATS_URL", "nats://nats:4222")
	otelEndpoint := envOr("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")
	authGRPCTarget := envOr("AUTH_GRPC_TARGET", "auth:9001")
	port := envOr("SERVICE_PORT", "8000")

	authClient, err := NewAuthClient(authGRPCTarget, logger)
	if err != nil {
		logger.Warn("auth gRPC unavailable, running without auth", "error", err)
	} else {
		gateway.authClient = authClient
		gateway.authCB = NewCircuitBreaker(3, 30*time.Second)
		defer authClient.Close()
	}

	rateLimit := envOr("RATE_LIMIT_PER_MIN", "100")
	rateLimitBurst := envOr("RATE_LIMIT_BURST", "10")
	rl := NewRateLimiter(parseInt(rateLimit, 100), parseInt(rateLimitBurst, 10))
	gateway.rateLimiter = rl
	defer rl.Stop()

	if err := gateway.InitNATS(natsURL); err != nil {
		logger.Warn("NATS not available, running without messaging", "error", err)
	}

	tp, err := gateway.InitOTel(otelEndpoint)
	if err != nil {
		logger.Warn("OTel not available", "error", err)
	} else {
		defer tp.Shutdown(context.Background())
	}

	allowedOrigins := envOr("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
	origins := splitCSV(allowedOrigins)
	corsHandler := cors.New(cors.Options{
		AllowedOrigins:   origins,
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"},
		AllowCredentials: true,
		MaxAge:           300,
	})
	handler := corsHandler.Handler(gateway.Routes())
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
		logger.Info("gateway starting", "port", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server error", "error", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	server.Shutdown(ctx)
	if gateway.nc != nil {
		gateway.nc.Close()
	}
	wg.Wait()
	logger.Info("shutdown complete")
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func parseInt(s string, defaultVal int) int {
	if s == "" {
		return defaultVal
	}
	var v int
	_, err := fmt.Sscanf(s, "%d", &v)
	if err != nil {
		return defaultVal
	}
	return v
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
