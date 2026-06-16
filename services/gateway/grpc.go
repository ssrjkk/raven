package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"math"
	"os"
	"time"

	pb "github.com/ssrjkk/raven/services/proto/go/auth/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

type AuthClient struct {
	conn   *grpc.ClientConn
	client pb.AuthServiceClient
	logger *slog.Logger
}

func retryInterceptor(logger *slog.Logger, maxRetries int) grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		req, reply interface{},
		cc *grpc.ClientConn,
		invoker grpc.UnaryInvoker,
		opts ...grpc.CallOption,
	) error {
		var lastErr error
		for attempt := 0; attempt <= maxRetries; attempt++ {
			if attempt > 0 {
				delay := time.Duration(math.Pow(2, float64(attempt-1))) * 100 * time.Millisecond
				if delay > 2*time.Second {
					delay = 2 * time.Second
				}
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(delay):
				}
			}
			err := invoker(ctx, method, req, reply, cc, opts...)
			if err == nil {
				return nil
			}
			st, ok := status.FromError(err)
			if !ok {
				return err
			}
			code := st.Code()
			if code == codes.Unavailable || code == codes.DeadlineExceeded || code == codes.ResourceExhausted {
				lastErr = err
				logger.Warn("gRPC retry", "method", method, "attempt", attempt, "error", err)
				continue
			}
			return err
		}
		return lastErr
	}
}

func NewAuthClient(target string, logger *slog.Logger) (*AuthClient, error) {
	dialOpts := []grpc.DialOption{
		grpc.WithUnaryInterceptor(retryInterceptor(logger, 2)),
		grpc.WithIdleTimeout(30 * time.Second),
	}

	certFile := os.Getenv("GRPC_TLS_CERT")
	caFile := os.Getenv("GRPC_TLS_CA")
	if certFile != "" && caFile != "" {
		caPEM, err := os.ReadFile(caFile)
		if err != nil {
			return nil, fmt.Errorf("read ca: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(caPEM) {
			return nil, fmt.Errorf("failed to parse CA cert")
		}
		creds := credentials.NewTLS(&tls.Config{RootCAs: pool})
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(creds))
		logger.Info("gRPC TLS enabled")
	} else {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := grpc.DialContext(ctx, target, dialOpts...)
	if err != nil {
		return nil, fmt.Errorf("grpc dial: %w", err)
	}
	return &AuthClient{
		conn:   conn,
		client: pb.NewAuthServiceClient(conn),
		logger: logger,
	}, nil
}

func (a *AuthClient) ValidateToken(ctx context.Context, token string) (string, string, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	resp, err := a.client.ValidateToken(ctx, &pb.ValidateTokenRequest{Token: token})
	if err != nil {
		return "", "", fmt.Errorf("validate token: %w", err)
	}
	if !resp.Valid {
		return "", "", fmt.Errorf("invalid token")
	}
	return resp.UserId, resp.Role, nil
}

func (a *AuthClient) Close() {
	if a.conn != nil {
		a.conn.Close()
	}
}
