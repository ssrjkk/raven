package main

import (
	"testing"
)

func TestSplitCSV(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  []string
	}{
		{"empty string returns nil", "", nil},
		{"single value", "a", []string{"a"}},
		{"two values", "a,b", []string{"a", "b"}},
		{"three values", "x,y,z", []string{"x", "y", "z"}},
		{"trailing comma", "a,b,", []string{"a", "b"}},
		{"leading comma", ",a,b", []string{"a", "b"}},
		{"whitespace not trimmed", "a , b", []string{"a ", " b"}},
		{"single char values", "1,2,3", []string{"1", "2", "3"}},
		{"url values", "http://a:8000,http://b:8001", []string{"http://a:8000", "http://b:8001"}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := splitCSV(tt.input)
			if len(got) != len(tt.want) {
				t.Errorf("splitCSV(%q) = %v (len=%d); want %v (len=%d)", tt.input, got, len(got), tt.want, len(tt.want))
				return
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Errorf("splitCSV(%q)[%d] = %q; want %q", tt.input, i, got[i], tt.want[i])
				}
			}
		})
	}
}

func TestEnvOr(t *testing.T) {
	t.Setenv("EXISTING_KEY", "existing_value")

	tests := []struct {
		name     string
		key      string
		def      string
		expected string
	}{
		{"existing env returns value", "EXISTING_KEY", "default", "existing_value"},
		{"missing env returns default", "MISSING_KEY", "fallback", "fallback"},
		{"empty env returns default", "EMPTY_KEY", "default_val", "default_val"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.key == "EMPTY_KEY" {
				t.Setenv(tt.key, "")
			}
			got := envOr(tt.key, tt.def)
			if got != tt.expected {
				t.Errorf("envOr(%q, %q) = %q; want %q", tt.key, tt.def, got, tt.expected)
			}
		})
	}
}

func TestNewAuthService(t *testing.T) {
	tests := []struct {
		name      string
		jwtSecret string
		wantKey   bool
	}{
		{"empty secret generates random key", "", true},
		{"valid hex secret is used", "abcdef0123456789abcdef0123456789", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := NewAuthService(tt.jwtSecret)
			if svc == nil {
				t.Fatal("NewAuthService returned nil")
			}
			if len(svc.jwtKey) == 0 {
				t.Error("expected non-empty jwtKey")
			}
			if svc.logger == nil {
				t.Error("expected non-nil logger")
			}
			if svc.rateLimiter == nil {
				t.Error("expected non-nil rateLimiter")
			}
		})
	}
}
