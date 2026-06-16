package main

import (
	"context"
	"database/sql"
	"log/slog"
	"os"
	"testing"

	_ "modernc.org/sqlite"
	pb "github.com/ssrjkk/raven/services/proto/go/auth/v1"
)

func newTestAuthService(t *testing.T) *AuthService {
	t.Helper()
	svc := NewAuthService(envOr("JWT_SECRET", "test-secret-123456789012345678901234567890"))
	db, err := sql.Open("sqlite", ":memory:?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		t.Fatalf("open :memory: db: %v", err)
	}
	svc.db = db
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS users (
		id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT,
		role TEXT DEFAULT 'user', created_at TEXT DEFAULT (datetime('now'))
	)`)
	if err != nil {
		t.Fatalf("create table: %v", err)
	}
	return svc
}

func TestAuthServiceRegister(t *testing.T) {
	svc := newTestAuthService(t)
	defer svc.db.Close()

	tests := []struct {
		name     string
		username string
		password string
		wantErr  bool
	}{
		{"valid registration", "alice", "password123!", false},
		{"short username", "ab", "password123!", true},
		{"short password", "bob", "short1!", true},
		{"duplicate username", "alice", "anotherPass1!", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			user, err := svc.register(context.Background(), tt.username, tt.password)
			if (err != nil) != tt.wantErr {
				t.Errorf("register(%q, %q) error = %v; wantErr = %v", tt.username, tt.password, err, tt.wantErr)
			}
			if !tt.wantErr {
				if user.ID == "" {
					t.Error("expected non-empty user ID")
				}
				if user.Username != tt.username {
					t.Errorf("expected username %q; got %q", tt.username, user.Username)
				}
				if user.Role != "user" {
					t.Errorf("expected role 'user'; got %q", user.Role)
				}
			}
		})
	}
}

func TestAuthServiceLogin(t *testing.T) {
	svc := newTestAuthService(t)
	defer svc.db.Close()

	_, err := svc.register(context.Background(), "loginuser", "securePass1!")
	if err != nil {
		t.Fatalf("register: %v", err)
	}

	tests := []struct {
		name     string
		username string
		password string
		wantErr  bool
	}{
		{"valid login", "loginuser", "securePass1!", false},
		{"wrong password", "loginuser", "wrongPass1!", true},
		{"nonexistent user", "nobody", "securePass1!", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			token, user, err := svc.login(context.Background(), tt.username, tt.password)
			if (err != nil) != tt.wantErr {
				t.Errorf("login(%q, %q) error = %v; wantErr = %v", tt.username, tt.password, err, tt.wantErr)
			}
			if !tt.wantErr {
				if token == "" {
					t.Error("expected non-empty token")
				}
				if user.Username != tt.username {
					t.Errorf("expected username %q; got %q", tt.username, user.Username)
				}
			}
		})
	}
}

func TestAuthServiceValidateToken(t *testing.T) {
	svc := newTestAuthService(t)
	defer svc.db.Close()

	_, err := svc.register(context.Background(), "tokenuser", "securePass1!")
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	token, _, err := svc.login(context.Background(), "tokenuser", "securePass1!")
	if err != nil {
		t.Fatalf("login: %v", err)
	}

	tests := []struct {
		name    string
		token   string
		wantErr bool
	}{
		{"valid token", token, false},
		{"invalid token", "bad.token.here", true},
		{"empty token", "", true},
		{"malformed token", "notajwt", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			claims, err := svc.validateToken(tt.token)
			if (err != nil) != tt.wantErr {
				t.Errorf("validateToken() error = %v; wantErr = %v", err, tt.wantErr)
			}
			if !tt.wantErr {
				if claims.UserID == "" {
					t.Error("expected non-empty user ID")
				}
				if claims.Role != "user" {
					t.Errorf("expected role 'user'; got %q", claims.Role)
				}
			}
		})
	}
}

func TestGRPCAuthServer(t *testing.T) {
	svc := newTestAuthService(t)
	defer svc.db.Close()

	svc.grpcServer = nil // prevent gRPC init in test
	server := &grpcAuthServer{svc: svc, logger: slog.New(slog.NewTextHandler(os.Stdout, nil))}

	svc.register(context.Background(), "grpcuser", "securePass1!")
	token, _, _ := svc.login(context.Background(), "grpcuser", "securePass1!")

	t.Run("valid token", func(t *testing.T) {
		resp, err := server.ValidateToken(context.Background(), &pb.ValidateTokenRequest{Token: token})
		if err != nil {
			t.Fatalf("ValidateToken: %v", err)
		}
		if !resp.Valid {
			t.Errorf("expected valid token")
		}
		if resp.UserId == "" {
			t.Error("expected non-empty user ID")
		}
	})

	t.Run("invalid token", func(t *testing.T) {
		resp, err := server.ValidateToken(context.Background(), &pb.ValidateTokenRequest{Token: "bad.token.str"})
		if err != nil {
			t.Fatalf("ValidateToken: %v", err)
		}
		if resp.Valid {
			t.Errorf("expected invalid token")
		}
	})

	t.Run("empty token", func(t *testing.T) {
		resp, err := server.ValidateToken(context.Background(), &pb.ValidateTokenRequest{Token: ""})
		if err != nil {
			t.Fatalf("ValidateToken: %v", err)
		}
		if resp.Valid {
			t.Errorf("expected invalid for empty token")
		}
	})

	t.Run("register valid user", func(t *testing.T) {
		resp, err := server.Register(context.Background(), &pb.RegisterRequest{
			Username: "newuser", Password: "securePass1!",
		})
		if err != nil {
			t.Fatalf("Register: %v", err)
		}
		if resp.UserId == "" {
			t.Error("expected non-empty user ID")
		}
	})

	t.Run("register duplicate user", func(t *testing.T) {
		_, err := server.Register(context.Background(), &pb.RegisterRequest{
			Username: "newuser", Password: "securePass1!",
		})
		if err == nil {
			t.Error("expected error for duplicate registration")
		}
	})

	t.Run("register short username", func(t *testing.T) {
		_, err := server.Register(context.Background(), &pb.RegisterRequest{
			Username: "ab", Password: "securePass1!",
		})
		if err == nil {
			t.Error("expected error for short username")
		}
	})

	t.Run("check permission user role", func(t *testing.T) {
		resp, err := server.CheckPermission(context.Background(), &pb.CheckPermissionRequest{
			UserId: "test", Role: "user", Resource: "monitors", Action: "read",
		})
		if err != nil {
			t.Fatalf("CheckPermission: %v", err)
		}
		if !resp.Allowed {
			t.Error("expected user role to be allowed")
		}
	})

	t.Run("check permission admin role", func(t *testing.T) {
		resp, _ := server.CheckPermission(context.Background(), &pb.CheckPermissionRequest{
			UserId: "test", Role: "admin", Resource: "monitors", Action: "delete",
		})
		if !resp.Allowed {
			t.Error("expected admin role to be allowed")
		}
	})

	t.Run("login via gRPC", func(t *testing.T) {
		resp, err := server.Login(context.Background(), &pb.LoginRequest{
			Username: "grpcuser", Password: "securePass1!",
		})
		if err != nil {
			t.Fatalf("Login: %v", err)
		}
		if resp.Token == "" {
			t.Error("expected non-empty token")
		}
	})

	t.Run("login invalid password", func(t *testing.T) {
		_, err := server.Login(context.Background(), &pb.LoginRequest{
			Username: "grpcuser", Password: "wrongPass1!",
		})
		if err == nil {
			t.Error("expected error for wrong password")
		}
	})
}
