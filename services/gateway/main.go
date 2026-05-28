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

type Gateway struct {
	nc      *nats.Conn
	js      jetstream.JetStream
	logger  *slog.Logger
	started time.Time

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

	mux.HandleFunc("POST /api/v1/auth/", g.proxyTo("http://auth:8001"))
	mux.HandleFunc("GET /api/v1/monitors", g.proxyTo("http://monitor-engine:8003"))
	mux.HandleFunc("POST /api/v1/monitors", g.proxyTo("http://monitor-engine:8003"))
	mux.HandleFunc("DELETE /api/v1/monitors/", g.proxyTo("http://monitor-engine:8003"))
	mux.HandleFunc("GET /api/v1/rag/", g.proxyTo("http://rag-service:8004"))
	mux.HandleFunc("POST /api/v1/rag/", g.proxyTo("http://rag-service:8004"))
	mux.HandleFunc("/api/v1/tasks/", g.proxyTo("http://task-engine:8005"))
	mux.HandleFunc("POST /api/v1/code/", g.proxyTo("http://code-service:8006"))
	mux.HandleFunc("/api/v1/agent/", g.proxyTo("http://agent-core:8002"))

	return otelhttp.NewHandler(g.metricsMiddleware(g.loggingMiddleware(mux)), "gateway")
}

func (g *Gateway) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		g.logger.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", sw.status,
			"duration_ms", time.Since(start).Milliseconds(),
			"remote", r.RemoteAddr,
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
		req, _ := http.NewRequestWithContext(r.Context(), r.Method, target, r.Body)
		req.Header = r.Header.Clone()
		resp, err := client.Do(req)
		if err != nil {
			g.logger.Error("proxy error", "target", target, "error", err)
			http.Error(w, `{"error":"upstream unreachable"}`, http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		for k, v := range resp.Header {
			w.Header()[k] = v
		}
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
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
	port := envOr("SERVICE_PORT", "8000")

	if err := gateway.InitNATS(natsURL); err != nil {
		logger.Warn("NATS not available, running without messaging", "error", err)
	}

	tp, err := gateway.InitOTel(otelEndpoint)
	if err != nil {
		logger.Warn("OTel not available", "error", err)
	} else {
		defer tp.Shutdown(context.Background())
	}

	handler := cors.AllowAll().Handler(gateway.Routes())
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
