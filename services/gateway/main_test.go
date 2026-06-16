package main

import (
	"net/http"
	"testing"
)

func TestSplitCSV(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  []string
	}{
		{"empty returns nil", "", nil},
		{"single value", "a", []string{"a"}},
		{"two values", "a,b", []string{"a", "b"}},
		{"three values", "x,y,z", []string{"x", "y", "z"}},
		{"trailing comma", "a,b,", []string{"a", "b"}},
		{"leading comma", ",a,b", []string{"a", "b"}},
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
	t.Setenv("GW_TEST_KEY", "test-value")

	tests := []struct {
		name     string
		key      string
		def      string
		expected string
	}{
		{"existing env returns value", "GW_TEST_KEY", "default", "test-value"},
		{"missing env returns default", "MISSING", "fallback", "fallback"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := envOr(tt.key, tt.def)
			if got != tt.expected {
				t.Errorf("envOr(%q, %q) = %q; want %q", tt.key, tt.def, got, tt.expected)
			}
		})
	}
}

func TestParseInt(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		def      int
		expected int
	}{
		{"valid number", "42", 0, 42},
		{"empty string uses default", "", 10, 10},
		{"invalid string uses default", "abc", 5, 5},
		{"negative number", "-5", 0, -5},
		{"zero", "0", 99, 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := parseInt(tt.input, tt.def)
			if got != tt.expected {
				t.Errorf("parseInt(%q, %d) = %d; want %d", tt.input, tt.def, got, tt.expected)
			}
		})
	}
}

func TestNewGateway(t *testing.T) {
	g := NewGateway()
	if g == nil {
		t.Fatal("NewGateway returned nil")
	}
	if g.logger == nil {
		t.Error("expected non-nil logger")
	}
	if g.rateLimiter != nil {
		t.Error("expected nil rate limiter before init")
	}
	if g.authClient != nil {
		t.Error("expected nil auth client before init")
	}
}

func TestStatusWriter(t *testing.T) {
	sw := &statusWriter{status: 200}
	sw.WriteHeader(http.StatusNotFound)
	if sw.status != 404 {
		t.Errorf("status = %d; want 404", sw.status)
	}
}
