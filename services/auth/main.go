package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
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
	"github.com/rs/cors"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
	_ "modernc.org/sqlite"
	"golang.org/x/crypto/bcrypt"
	"google.golang.org/grpc"
)

type contextKey string

const contextReqID contextKey = "req_id"

type AuthService struct {
	db      *sql.DB
	nc      *nats.Conn
	js      jetstream.JetStream
	jwtKey  []byte
	logger  *slog.Logger
	started time.Time
	mu      sync.RWMutex

	grpcServer *grpc.Server
	rateLimiter *RateLimiter

	httpRequests *prometheus.CounterVec
	httpDuration *prometheus.HistogramVec
}

type User struct {
	ID        string
	Username  string
	Password  string
	Role      string
	CreatedAt string
}

type TokenClaims struct {
	UserID string
	Role   string
}

func NewAuthService(jwtSecret string) *AuthService {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	key, err := hex.DecodeString(jwtSecret)
	if len(key) == 0 || err != nil {
		key = make([]byte, 32)
		if _, err := rand.Read(key); err != nil {
			logger.Error("failed to generate random key", "error", err)
		}
	}

	return &AuthService{
		jwtKey:  key,
		logger:  logger,
		started: time.Now(),
		rateLimiter: NewRateLimiter(200, 20),
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
	s.db, err = sql.Open("sqlite", path+"?_journal_mode=WAL&_busy_timeout=5000")
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

func (s *AuthService) register(ctx context.Context, username, password string) (User, error) {
	if len(username) < 3 || len(password) < 8 {
		return User{}, fmt.Errorf("username min 3, password min 8")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return User{}, fmt.Errorf("bcrypt: %w", err)
	}
	id := uuid.New().String()
	_, err = s.db.ExecContext(ctx,
		"INSERT INTO users (id, username, password, role) VALUES (?, ?, ?, 'user')",
		id, username, string(hash))
	if err != nil {
		return User{}, fmt.Errorf("insert: %w", err)
	}
	s.logger.Info("user registered", "user_id", id, "username", username)
	if s.js != nil {
		evt, _ := json.Marshal(map[string]string{"user_id": id, "username": username})
		if _, err := s.js.Publish(ctx, "auth.user.created", evt); err != nil {
			s.logger.Warn("failed to publish auth.user.created", "error", err)
		}
	}
	return User{ID: id, Username: username, Role: "user"}, nil
}

func (s *AuthService) login(ctx context.Context, username, password string) (string, User, error) {
	var user User
	err := s.db.QueryRowContext(ctx,
		"SELECT id, username, password, role, created_at FROM users WHERE username = ?",
		username).Scan(&user.ID, &user.Username, &user.Password, &user.Role, &user.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return "", User{}, fmt.Errorf("invalid credentials")
	}
	if err != nil {
		return "", User{}, fmt.Errorf("db: %w", err)
	}
	if err := bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(password)); err != nil {
		return "", User{}, fmt.Errorf("invalid credentials")
	}
	expires := time.Now().Add(24 * time.Hour)
	claims := jwt.MapClaims{"sub": user.ID, "role": user.Role, "exp": expires.Unix()}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString(s.jwtKey)
	if err != nil {
		return "", User{}, fmt.Errorf("jwt sign: %w", err)
	}
	return tokenStr, user, nil
}

func (s *AuthService) validateToken(tokenStr string) (TokenClaims, error) {
	token, err := jwt.Parse(tokenStr, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return s.jwtKey, nil
	})
	if err != nil || !token.Valid {
		return TokenClaims{}, fmt.Errorf("invalid token")
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return TokenClaims{}, fmt.Errorf("invalid claims")
	}
	sub, _ := claims.GetSubject()
	role, _ := claims["role"].(string)
	if sub == "" {
		return TokenClaims{}, fmt.Errorf("missing subject")
	}
	return TokenClaims{UserID: sub, Role: role}, nil
}

func (s *AuthService) Routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "healthy", "service": "auth"})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if s.db == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	mux.Handle("GET /metrics", promhttp.Handler())

	mux.HandleFunc("POST /api/v1/auth/register", s.httpRegister)
	mux.HandleFunc("POST /api/v1/auth/login", s.httpLogin)
	mux.HandleFunc("POST /api/v1/auth/validate", s.httpValidate)

	rateLimited := s.rateLimitMiddleware(s.metricsMiddleware(s.requestIDMiddleware(s.loggingMiddleware(mux))))
	return otelhttp.NewHandler(rateLimited, "auth")
}

func (s *AuthService) httpRegister(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
		return
	}
	user, err := s.register(r.Context(), body.Username, body.Password)
	if err != nil {
		if err.Error() == "username min 3, password min 8" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		} else {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "username exists"})
		}
		return
	}
	w.WriteHeader(http.StatusCreated)
	writeJSON(w, http.StatusCreated, map[string]string{"user_id": user.ID})
}

func (s *AuthService) httpLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
		return
	}
	tokenStr, user, err := s.login(r.Context(), body.Username, body.Password)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid credentials"})
		return
	}
	expires := time.Now().Add(24 * time.Hour)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"token": tokenStr, "expires_at": expires.Unix(), "user_id": user.ID,
	})
}

func (s *AuthService) httpValidate(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]interface{}{"valid": false})
		return
	}
	claims, err := s.validateToken(body.Token)
	if err != nil {
		w.WriteHeader(http.StatusUnauthorized)
		writeJSON(w, http.StatusUnauthorized, map[string]interface{}{"valid": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"valid": true, "user_id": claims.UserID, "role": claims.Role,
	})
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func (s *AuthService) requestIDMiddleware(next http.Handler) http.Handler {
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

func (s *AuthService) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: 200}
		reqID, _ := r.Context().Value(contextReqID).(string)
		next.ServeHTTP(sw, r)
		s.logger.Info("request",
			"method", r.Method, "path", r.URL.Path,
			"status", sw.status, "duration_ms", time.Since(start).Milliseconds(),
			"req_id", reqID, "remote", r.RemoteAddr,
		)
	})
}

func (s *AuthService) rateLimitMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ip := r.RemoteAddr
		if idx := len(ip) - 1; idx >= 0 {
			for i := len(ip) - 1; i >= 0; i-- {
				if ip[i] == ':' {
					ip = ip[:i]
					break
				}
			}
		}
		if !s.rateLimiter.Allow(ip) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusTooManyRequests)
			json.NewEncoder(w).Encode(map[string]string{"error": "rate limited"})
			return
		}
		next.ServeHTTP(w, r)
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
	grpcPort := envOr("GRPC_PORT", "9001")
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

	if err := svc.startGRPC(grpcPort); err != nil {
		logger.Warn("gRPC server unavailable", "error", err)
	}

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		logger.Info("auth starting", "http_port", port, "grpc_port", grpcPort)
		server.ListenAndServe()
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info("shutting down")
	if svc.grpcServer != nil {
		svc.grpcServer.GracefulStop()
	}
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
