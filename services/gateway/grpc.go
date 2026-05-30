package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"os"
	"time"

	pb "github.com/ssrjkk/raven/services/proto/go/auth/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
)

type AuthClient struct {
	conn   *grpc.ClientConn
	client pb.AuthServiceClient
	logger *slog.Logger
}

func NewAuthClient(target string, logger *slog.Logger) (*AuthClient, error) {
	dialOpts := []grpc.DialOption{grpc.WithTimeout(5 * time.Second)}

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

	conn, err := grpc.NewClient(target, dialOpts...)
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
