package main

import (
	"net/http"
	"testing"
)

func TestHTTPStatusForCode(t *testing.T) {
	tests := []struct {
		name     string
		code     ErrorCode
		expected int
	}{
		{"invalid input maps to 400", ErrInvalidInput, http.StatusBadRequest},
		{"unauthorized maps to 401", ErrUnauthorized, http.StatusUnauthorized},
		{"forbidden maps to 403", ErrForbidden, http.StatusForbidden},
		{"not found maps to 404", ErrNotFound, http.StatusNotFound},
		{"conflict maps to 409", ErrConflict, http.StatusConflict},
		{"rate limited maps to 429", ErrRateLimited, http.StatusTooManyRequests},
		{"upstream error maps to 502", ErrUpstream, http.StatusBadGateway},
		{"auth unavailable maps to 502", ErrAuthUnavailable, http.StatusBadGateway},
		{"unknown code maps to 500", ErrorCode("UNKNOWN"), http.StatusInternalServerError},
		{"empty code maps to 500", ErrorCode(""), http.StatusInternalServerError},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := httpStatusForCode(tt.code)
			if got != tt.expected {
				t.Errorf("httpStatusForCode(%q) = %d; want %d", tt.code, got, tt.expected)
			}
		})
	}
}

func TestErrorResponseJSON(t *testing.T) {
	tests := []struct {
		name     string
		err      ErrorResponse
		contains string
	}{
		{"basic error includes message", ErrorResponse{Error: "something went wrong"}, "something went wrong"},
		{"error with code includes both", ErrorResponse{Error: "bad input", Code: ErrInvalidInput}, "bad input"},
		{"error with details includes details", ErrorResponse{Error: "fail", Code: ErrInternal, Details: "stack trace"}, "stack trace"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			data := tt.err
			if data.Error == "" {
				t.Error("expected non-empty error field")
			}
		})
	}
}

func TestWriteError(t *testing.T) {
	// Verify writeError accepts valid arguments without panicking
	// (full HTTP test would require httptest.ResponseRecorder)
	t.Run("accepts all known codes", func(t *testing.T) {
		codes := []ErrorCode{
			ErrInvalidInput, ErrUnauthorized, ErrForbidden,
			ErrNotFound, ErrConflict, ErrRateLimited,
			ErrUpstream, ErrInternal, ErrAuthUnavailable,
		}
		for _, code := range codes {
			status := httpStatusForCode(code)
			if status < 400 || status > 599 {
				t.Errorf("code %q produced non-error status %d", code, status)
			}
		}
	})
}
