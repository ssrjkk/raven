package main

import (
	"context"
	"errors"
	"log/slog"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type testInvoker struct {
	attempts int
	errs     []error
}

func (ti *testInvoker) invoke(ctx context.Context, method string, req, reply interface{}, cc *grpc.ClientConn, opts ...grpc.CallOption) error {
	if ti.attempts < len(ti.errs) {
		err := ti.errs[ti.attempts]
		ti.attempts++
		return err
	}
	return nil
}

func TestRetryInterceptor(t *testing.T) {
	logger := slog.Default()

	tests := []struct {
		name       string
		maxRetries int
		errs       []error
		wantErr    bool
	}{
		{
			name:       "no error succeeds immediately",
			maxRetries: 2,
			errs:       nil,
			wantErr:    false,
		},
		{
			name:       "transient error retried then succeeds",
			maxRetries: 2,
			errs:       []error{status.Error(codes.Unavailable, "unavailable"), nil},
			wantErr:    false,
		},
		{
			name:       "all transient errors eventually fail",
			maxRetries: 2,
			errs: []error{
				status.Error(codes.Unavailable, "unavailable 1"),
				status.Error(codes.Unavailable, "unavailable 2"),
				status.Error(codes.Unavailable, "unavailable 3"),
			},
			wantErr: true,
		},
		{
			name:       "non-transient error fails immediately",
			maxRetries: 2,
			errs:       []error{status.Error(codes.InvalidArgument, "bad arg")},
			wantErr:    true,
		},
		{
			name:       "deadline exceeded retried",
			maxRetries: 1,
			errs:       []error{status.Error(codes.DeadlineExceeded, "timeout"), nil},
			wantErr:    false,
		},
		{
			name:       "resource exhausted retried",
			maxRetries: 1,
			errs:       []error{status.Error(codes.ResourceExhausted, "ratelimit"), nil},
			wantErr:    false,
		},
		{
			name:       "non-grpc error fails immediately",
			maxRetries: 2,
			errs:       []error{errors.New("network error")},
			wantErr:    true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			interceptor := retryInterceptor(logger, tt.maxRetries)
			ti := &testInvoker{errs: tt.errs}

			invoker := func(ctx context.Context, method string, req, reply interface{}, cc *grpc.ClientConn, opts ...grpc.CallOption) error {
				return ti.invoke(ctx, method, req, reply, cc, opts...)
			}

			err := interceptor(context.Background(), "TestMethod", nil, nil, nil, invoker)
			if (err != nil) != tt.wantErr {
				t.Errorf("retryInterceptor error = %v; wantErr = %v", err, tt.wantErr)
			}
		})
	}
}

func TestRetryInterceptorContextCancelled(t *testing.T) {
	logger := slog.Default()
	interceptor := retryInterceptor(logger, 2)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	ti := &testInvoker{errs: []error{status.Error(codes.Unavailable, "unavailable")}}
	invoker := func(ctx context.Context, method string, req, reply interface{}, cc *grpc.ClientConn, opts ...grpc.CallOption) error {
		return ti.invoke(ctx, method, req, reply, cc, opts...)
	}

	err := interceptor(ctx, "TestMethod", nil, nil, nil, invoker)
	if err == nil {
		t.Error("expected error from cancelled context")
	}
}
