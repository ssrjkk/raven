package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	pb "github.com/ssrjkk/raven/services/proto/go/auth/v1"
	"golang.org/x/crypto/bcrypt"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
)

var (
	grpcRequests = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "grpc_requests_total",
		Help: "Total gRPC requests",
	}, []string{"method", "code"})
	grpcDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "grpc_request_duration_seconds",
		Help:    "gRPC request duration",
		Buckets: prometheus.DefBuckets,
	}, []string{"method"})
)

func unaryInterceptor(logger *slog.Logger) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
		start := time.Now()
		resp, err := handler(ctx, req)
		code := status.Code(err)
		duration := time.Since(start).Seconds()
		grpcRequests.WithLabelValues(info.FullMethod, code.String()).Inc()
		grpcDuration.WithLabelValues(info.FullMethod).Observe(duration)
		logger.Info("gRPC", "method", info.FullMethod, "code", code.String(), "duration_ms", time.Since(start).Milliseconds())
		return resp, err
	}
}

type grpcAuthServer struct {
	pb.UnimplementedAuthServiceServer
	db     *sql.DB
	jwtKey []byte
	logger *slog.Logger
}

func (s *AuthService) startGRPC(port string) error {
	lis, err := net.Listen("tcp", ":"+port)
	if err != nil {
		return fmt.Errorf("grpc listen: %w", err)
	}

	var opts []grpc.ServerOption
	opts = append(opts, grpc.UnaryInterceptor(unaryInterceptor(s.logger)))
	certFile := os.Getenv("GRPC_TLS_CERT")
	keyFile := os.Getenv("GRPC_TLS_KEY")
	if certFile != "" && keyFile != "" {
		creds, err := credentials.NewServerTLSFromFile(certFile, keyFile)
		if err != nil {
			return fmt.Errorf("grpc tls: %w", err)
		}
		opts = append(opts, grpc.Creds(creds))
		s.logger.Info("gRPC TLS enabled")
	}

	s.grpcServer = grpc.NewServer(opts...)
	pb.RegisterAuthServiceServer(s.grpcServer, &grpcAuthServer{
		db:     s.db,
		jwtKey: s.jwtKey,
		logger: s.logger,
	})
	healthSrv := health.NewServer()
	healthSrv.SetServingStatus("", grpc_health_v1.HealthCheckResponse_SERVING)
	grpc_health_v1.RegisterHealthServer(s.grpcServer, healthSrv)
	go func() {
		s.logger.Info("gRPC server starting", "port", port)
		if err := s.grpcServer.Serve(lis); err != nil {
			s.logger.Error("gRPC server error", "error", err)
		}
	}()
	return nil
}

func (s *grpcAuthServer) Login(ctx context.Context, req *pb.LoginRequest) (*pb.LoginResponse, error) {
	var id, username, password, role string
	err := s.db.QueryRow(
		"SELECT id, username, password, role FROM users WHERE username = ?",
		req.Username,
	).Scan(&id, &username, &password, &role)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, status.Error(codes.Unauthenticated, "invalid credentials")
	}
	if err != nil {
		return nil, status.Error(codes.Internal, "database error")
	}
	if err := bcrypt.CompareHashAndPassword([]byte(password), []byte(req.Password)); err != nil {
		return nil, status.Error(codes.Unauthenticated, "invalid credentials")
	}
	expires := time.Now().Add(24 * time.Hour)
	claims := jwt.MapClaims{"sub": id, "role": role, "exp": expires.Unix()}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, _ := token.SignedString(s.jwtKey)

	return &pb.LoginResponse{
		Token:    tokenStr,
		UserId:   id,
		Role:     role,
		Username: username,
	}, nil
}

func (s *grpcAuthServer) Register(ctx context.Context, req *pb.RegisterRequest) (*pb.RegisterResponse, error) {
	if len(req.Username) < 3 || len(req.Password) < 8 {
		return nil, status.Error(codes.InvalidArgument, "username min 3, password min 8")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		return nil, status.Error(codes.Internal, "bcrypt error")
	}
	id := uuid.New().String()
	_, err = s.db.Exec(
		"INSERT INTO users (id, username, password, role) VALUES (?, ?, ?, 'user')",
		id, req.Username, string(hash),
	)
	if err != nil {
		return nil, status.Error(codes.AlreadyExists, "username already exists")
	}
	s.logger.Info("gRPC user registered", "user_id", id, "username", req.Username)
	return &pb.RegisterResponse{UserId: id, Role: "user", Username: req.Username}, nil
}

func (s *grpcAuthServer) ValidateToken(ctx context.Context, req *pb.ValidateTokenRequest) (*pb.ValidateTokenResponse, error) {
	token, err := jwt.Parse(req.Token, func(t *jwt.Token) (interface{}, error) {
		return s.jwtKey, nil
	})
	if err != nil || !token.Valid {
		return &pb.ValidateTokenResponse{Valid: false}, nil
	}
	claims := token.Claims.(jwt.MapClaims)
	return &pb.ValidateTokenResponse{
		Valid:  true,
		UserId: claims["sub"].(string),
		Role:   claims["role"].(string),
	}, nil
}

func (s *grpcAuthServer) CheckPermission(ctx context.Context, req *pb.CheckPermissionRequest) (*pb.CheckPermissionResponse, error) {
	return &pb.CheckPermissionResponse{Allowed: req.Role == "user" || req.Role == "admin"}, nil
}

func (s *grpcAuthServer) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.GetUserResponse, error) {
	var id, username, role string
	err := s.db.QueryRow(
		"SELECT id, username, role FROM users WHERE id = ?", req.UserId,
	).Scan(&id, &username, &role)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, status.Error(codes.NotFound, "user not found")
	}
	if err != nil {
		return nil, status.Error(codes.Internal, "database error")
	}
	return &pb.GetUserResponse{
		UserId:   id,
		Username: username,
		Role:     role,
	}, nil
}

func (s *grpcAuthServer) UpdateRole(ctx context.Context, req *pb.UpdateRoleRequest) (*pb.UpdateRoleResponse, error) {
	_, err := s.db.Exec("UPDATE users SET role = ? WHERE id = ?", req.Role, req.UserId)
	if err != nil {
		return nil, status.Error(codes.Internal, "update failed")
	}
	return &pb.UpdateRoleResponse{Ok: true}, nil
}


