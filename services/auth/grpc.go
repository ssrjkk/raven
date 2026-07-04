package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	pb "github.com/ssrjkk/raven/services/proto/go/auth/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func unaryInterceptor(logger *slog.Logger, grpcRequests *prometheus.CounterVec, grpcDuration *prometheus.HistogramVec) grpc.UnaryServerInterceptor {
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
	svc    *AuthService
	logger *slog.Logger
}

func (s *AuthService) startGRPC(port string) error {
	lis, err := net.Listen("tcp", ":"+port)
	if err != nil {
		return fmt.Errorf("grpc listen: %w", err)
	}

	var opts []grpc.ServerOption
	opts = append(opts, grpc.UnaryInterceptor(unaryInterceptor(s.logger, s.grpcRequests, s.grpcDuration)))
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
		svc:    s,
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

func (g *grpcAuthServer) Login(ctx context.Context, req *pb.LoginRequest) (*pb.LoginResponse, error) {
	tokenStr, user, err := g.svc.login(ctx, req.Username, req.Password)
	if err != nil {
		if err.Error() == "invalid credentials" {
			return nil, status.Error(codes.Unauthenticated, "invalid credentials")
		}
		return nil, status.Error(codes.Internal, "login failed")
	}
	return &pb.LoginResponse{
		Token:    tokenStr,
		UserId:   user.ID,
		Role:     user.Role,
		Username: user.Username,
	}, nil
}

func (g *grpcAuthServer) Register(ctx context.Context, req *pb.RegisterRequest) (*pb.RegisterResponse, error) {
	user, err := g.svc.register(ctx, req.Username, req.Password)
	if err != nil {
		if err.Error() == "username min 3, password min 8" {
			return nil, status.Error(codes.InvalidArgument, err.Error())
		}
		return nil, status.Error(codes.AlreadyExists, "username already exists")
	}
	return &pb.RegisterResponse{UserId: user.ID, Role: user.Role, Username: user.Username}, nil
}

func (g *grpcAuthServer) ValidateToken(ctx context.Context, req *pb.ValidateTokenRequest) (*pb.ValidateTokenResponse, error) {
	claims, err := g.svc.validateToken(req.Token)
	if err != nil {
		return &pb.ValidateTokenResponse{Valid: false}, nil
	}
	return &pb.ValidateTokenResponse{
		Valid:  true,
		UserId: claims.UserID,
		Role:   claims.Role,
	}, nil
}

func bearerToken(ctx context.Context) string {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return ""
	}
	vals := md.Get("authorization")
	if len(vals) == 0 {
		return ""
	}
	return strings.TrimPrefix(vals[0], "Bearer ")
}

func (g *grpcAuthServer) CheckPermission(ctx context.Context, req *pb.CheckPermissionRequest) (*pb.CheckPermissionResponse, error) {
	token := bearerToken(ctx)
	claims, err := g.svc.validateToken(token)
	if err != nil {
		return &pb.CheckPermissionResponse{Allowed: false}, nil
	}
	allowed := false
	switch req.Permission {
	case "read":
		allowed = claims.Role == "admin" || claims.Role == "user" || claims.Role == "viewer"
	case "write":
		allowed = claims.Role == "admin" || claims.Role == "user"
	case "delete":
		allowed = claims.Role == "admin"
	case "admin":
		allowed = claims.Role == "admin"
	default:
		allowed = false
	}
	return &pb.CheckPermissionResponse{Allowed: allowed}, nil
}

func (g *grpcAuthServer) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.GetUserResponse, error) {
	var id, username, role string
	err := g.svc.db.QueryRowContext(ctx,
		"SELECT id, username, role FROM users WHERE id = ?", req.UserId,
	).Scan(&id, &username, &role)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, status.Error(codes.NotFound, "user not found")
	}
	if err != nil {
		return nil, status.Error(codes.Internal, "database error")
	}
	return &pb.GetUserResponse{UserId: id, Username: username, Role: role}, nil
}

func (g *grpcAuthServer) UpdateRole(ctx context.Context, req *pb.UpdateRoleRequest) (*pb.UpdateRoleResponse, error) {
	_, err := g.svc.db.ExecContext(ctx, "UPDATE users SET role = ? WHERE id = ?", req.Role, req.UserId)
	if err != nil {
		return nil, status.Error(codes.Internal, "update failed")
	}
	return &pb.UpdateRoleResponse{Ok: true}, nil
}
