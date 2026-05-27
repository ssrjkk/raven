package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
	"golang.org/x/crypto/bcrypt"
)

type AuthService struct {
	db      *sql.DB
	nc      *nats.Conn
	js      jetstream.JetStream
	jwtKey  []byte
	logger  *slog.Logger
	started time.Time
	mu      sync.RWMutex

	httpRequests *prometheus.CounterVec
	httpDuration *prometheus.HistogramVec
}

type User struct {
	ID        string `json:"id"`
	Username  string `json:"username"`
	Password  string `json:"-"`
	Role      string `json:"role"`
	CreatedAt string `json:"created_at"`
}

type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type RegisterRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type TokenResponse struct {
	Token     string `json:"token"`
	ExpiresAt int64  `json:"expires_at"`
	UserID    string `json:"user_id"`
}

type ValidateRequest struct {
	Token string `json:"token"`
}

type ValidateResponse struct {
	Valid  bool   `json:"valid"`
	UserID string `json:"user_id"`
	Role   string `json:"role"`
}

func NewAuthService(jwtSecret string) *AuthService {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	key, _ := hex.DecodeString(jwtSecret)
	if len(key) == 0 {
		key = make([]byte, 32)
		rand.Read(key)
	}

	return &AuthService{
		jwtKey:  key,
		logger:  logger,
		started: time.Now(),
		httpRequests: prometheus.NewCounterVec(
			prometheus.CounterOpts{Name: "auth_requests_total", Help: "Auth requests"},
			[]string{"method", "path", "status"},
		),
		httpDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{Name: "auth_request_duration_seconds", Help: "Request duration",
				Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1}},
			[]string{"method", "path"},
		),
	}
}

func (s *AuthService) InitDB(path string) error {
	var err error
	s.db, err = sql.Open("sqlite3", path+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		return fmt.Errorf("sqlite open: %w", err)
	}
	s.db.SetMaxOpenConns(1)
	_, err = s.db.Exec(`CREATE TABLE IF NOT EXISTS users (
		id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT,
		role TEXT DEFAULT 'user', created_at TEXT DEFAULT (datetime('now'))
	)`)
	if err != nil {
		return fmt.Errorf("migrate: %w", err)
	}
	return nil
}

func (s *AuthService) InitNATS(url string) error {
	nc, err := nats.Connect(url, nats.Name("auth"))
	if err != nil {
		return fmt.Errorf("nats: %w", err)
	}
	s.nc = nc
	js, err := jetstream.New(nc)
	if err != nil {
		return fmt.Errorf("jetstream: %w", err)
	}
	s.js = js
	return nil
}

func (s *AuthService) InitOTel(endpoint string) (*sdktrace.TracerProvider, error) {
	exporter, err := otlptracegrpc.New(context.Background(),
		otlptracegrpc.WithEndpoint(endpoint), otlptracegrpc.WithInsecure())
	if err != nil {
		return nil, err
	}
	res := resource.NewWithAttributes(semconv.SchemaURL,
		semconv.ServiceNameKey.String("auth"),
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

func (s *AuthService) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{"status": "healthy", "service": "auth"})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		if s.db == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	mux.Handle("GET /metrics", promhttp.Handler())

	mux.HandleFunc("POST /api/v1/auth/register", s.handleRegister)
	mux.HandleFunc("POST /api/v1/auth/login", s.handleLogin)
	mux.HandleFunc("POST /api/v1/auth/validate", s.handleValidate)

	return otelhttp.NewHandler(s.metricsMiddleware(s.loggingMiddleware(mux)), "auth")
}

func (s *AuthService) handleRegister(w http.ResponseWriter, r *http.Request) {
	var req RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid body"}`, http.StatusBadRequest)
		return
	}
	if len(req.Username) < 3 || len(req.Password) < 8 {
		http.Error(w, `{"error":"username min 3, password min 8"}`, http.StatusBadRequest)
		return
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		http.Error(w, `{"error":"internal"}`, http.StatusInternalServerError)
		return
	}

	id := uuid.New().String()
	_, err = s.db.Exec("INSERT INTO users (id, username, password, role) VALUES (?, ?, ?, 'user')",
		id, req.Username, string(hash))
	if err != nil {
		http.Error(w, `{"error":"username exists"}`, http.StatusConflict)
		return
	}
	s.logger.Info("user registered", "user_id", id, "username", req.Username)

	// Publish event via NATS
	if s.js != nil {
		evt, _ := json.Marshal(map[string]string{"user_id": id, "username": req.Username})
		s.js.Publish(r.Context(), "auth.user.created", evt)
	}

	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]string{"user_id": id})
}

func (s *AuthService) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid body"}`, http.StatusBadRequest)
		return
	}

	var user User
	err := s.db.QueryRow("SELECT id, username, password, role FROM users WHERE username = ?",
		req.Username).Scan(&user.ID, &user.Username, &user.Password, &user.Role)
	if err != nil {
		http.Error(w, `{"error":"invalid credentials"}`, http.StatusUnauthorized)
		return
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(req.Password)); err != nil {
		http.Error(w, `{"error":"invalid credentials"}`, http.StatusUnauthorized)
		return
	}

	expires := time.Now().Add(24 * time.Hour)
	claims := jwt.MapClaims{
		"sub": user.ID, "role": user.Role, "exp": expires.Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, _ := token.SignedString(s.jwtKey)

	json.NewEncoder(w).Encode(TokenResponse{
		Token: tokenStr, ExpiresAt: expires.Unix(), UserID: user.ID,
	})
}

func (s *AuthService) handleValidate(w http.ResponseWriter, r *http.Request) {
	var req ValidateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid body"}`, http.StatusBadRequest)
		return
	}

	token, err := jwt.Parse(req.Token, func(t *jwt.Token) (interface{}, error) {
		return s.jwtKey, nil
	})
	if err != nil || !token.Valid {
		json.NewEncoder(w).Encode(ValidateResponse{Valid: false})
		return
	}

	claims := token.Claims.(jwt.MapClaims)
	json.NewEncoder(w).Encode(ValidateResponse{
		Valid: true, UserID: claims["sub"].(string), Role: claims["role"].(string),
	})
}

func (s *AuthService) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		s.logger.Info("request", "method", r.Method, "path", r.URL.Path,
			"status", sw.status, "duration_ms", time.Since(start).Milliseconds())
	})
}

func (s *AuthService) metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(sw, r)
		s.httpRequests.WithLabelValues(r.Method, r.URL.Path, fmt.Sprint(sw.status)).Inc()
		s.httpDuration.WithLabelValues(r.Method, r.URL.Path).Observe(time.Since(start).Seconds())
	})
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
	svc := NewAuthService(envOr("JWT_SECRET", ""))

	if err := svc.InitDB(envOr("DB_PATH", "/data/auth.db")); err != nil {
		logger.Error("db init failed", "error", err)
		os.Exit(1)
	}

	if err := svc.InitNATS(envOr("NATS_URL", "nats://nats:4222")); err != nil {
		logger.Warn("NATS unavailable", "error", err)
	}

	tp, err := svc.InitOTel(envOr("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317"))
	if err == nil {
		defer tp.Shutdown(context.Background())
	}

	port := envOr("SERVICE_PORT", "8001")
	server := &http.Server{
		Addr:    ":" + port,
		Handler: svc.Routes(),
	}

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		logger.Info("auth starting", "port", port)
		server.ListenAndServe()
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info("shutting down")
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
