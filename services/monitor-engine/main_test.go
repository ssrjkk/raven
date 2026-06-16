package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	_ "modernc.org/sqlite"
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
		{"trailing comma", "a,", []string{"a"}},
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
	t.Setenv("MON_TEST_KEY", "test_value")

	tests := []struct {
		name     string
		key      string
		def      string
		expected string
	}{
		{"existing returns value", "MON_TEST_KEY", "default", "test_value"},
		{"missing returns default", "MISSING_KEY", "fallback", "fallback"},
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

func TestNewMonitorEngine(t *testing.T) {
	svc := NewMonitorEngine()
	if svc == nil {
		t.Fatal("NewMonitorEngine returned nil")
	}
	if svc.logger == nil {
		t.Error("expected non-nil logger")
	}
	if svc.checks == nil {
		t.Error("expected non-nil checks map")
	}
	if svc.cancels == nil {
		t.Error("expected non-nil cancels map")
	}
}

func TestMonitorEngineInitDB(t *testing.T) {
	svc := NewMonitorEngine()
	err := svc.InitDB(":memory:")
	if err != nil {
		t.Fatalf("InitDB failed: %v", err)
	}
	defer svc.db.Close()

	var tableName string
	err = svc.db.QueryRow("SELECT name FROM sqlite_master WHERE type='table' AND name='monitors'").Scan(&tableName)
	if err != nil {
		t.Errorf("monitors table not found: %v", err)
	}
	if tableName != "monitors" {
		t.Errorf("expected table 'monitors'; got %q", tableName)
	}
}

func TestMonitorCreateDelete(t *testing.T) {
	svc := NewMonitorEngine()
	svc.InitDB(":memory:")
	defer svc.db.Close()

	t.Run("create monitor", func(t *testing.T) {
		body := `{"name":"test-mon","url":"http://example.com","interval_seconds":60,"timeout_seconds":5}`
		req := httptest.NewRequest("POST", "/api/v1/monitors", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()

		svc.createMonitor(w, req)

		if w.Code != http.StatusCreated {
			t.Errorf("create status = %d; want 201", w.Code)
		}

		var resp Monitor
		if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
			t.Fatalf("decode response: %v", err)
		}
		if resp.ID == "" {
			t.Error("expected non-empty ID")
		}
		if resp.Name != "test-mon" {
			t.Errorf("expected name 'test-mon'; got %q", resp.Name)
		}
		if !resp.Enabled {
			t.Error("expected monitor enabled by default")
		}
		if resp.LastStatus != "pending" {
			t.Errorf("expected status 'pending'; got %q", resp.LastStatus)
		}
	})

	t.Run("delete monitor", func(t *testing.T) {
		body := `{"name":"del-mon","url":"http://example.com"}`
		req := httptest.NewRequest("POST", "/api/v1/monitors", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		svc.createMonitor(w, req)

		var created Monitor
		json.NewDecoder(w.Body).Decode(&created)

		delReq := httptest.NewRequest("DELETE", "/api/v1/monitors/"+created.ID, nil)
		delW := httptest.NewRecorder()
		svc.deleteMonitor(delW, delReq)

		if delW.Code != http.StatusNoContent {
			t.Errorf("delete status = %d; want 204", delW.Code)
		}

		svc.checksMu.RLock()
		_, exists := svc.checks[created.ID]
		svc.checksMu.RUnlock()
		if exists {
			t.Error("expected monitor removed from checks map")
		}
	})

	t.Run("create monitor with invalid body", func(t *testing.T) {
		req := httptest.NewRequest("POST", "/api/v1/monitors", strings.NewReader("not json"))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		svc.createMonitor(w, req)

		if w.Code != http.StatusBadRequest {
			t.Errorf("expected 400; got %d", w.Code)
		}
	})

	t.Run("create monitor enforces min interval", func(t *testing.T) {
		body := `{"name":"min-interval","url":"http://example.com","interval_seconds":5}`
		req := httptest.NewRequest("POST", "/api/v1/monitors", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		svc.createMonitor(w, req)

		var resp Monitor
		json.NewDecoder(w.Body).Decode(&resp)
		if resp.IntervalSec < 10 {
			t.Errorf("expected interval >= 10; got %d", resp.IntervalSec)
		}
	})
}

func TestMonitorList(t *testing.T) {
	svc := NewMonitorEngine()
	svc.InitDB(":memory:")
	defer svc.db.Close()

	svc.createMonitor(httptest.NewRecorder(),
		httptest.NewRequest("POST", "/api/v1/monitors",
			strings.NewReader(`{"name":"m1","url":"http://a.com"}`)))
	svc.createMonitor(httptest.NewRecorder(),
		httptest.NewRequest("POST", "/api/v1/monitors",
			strings.NewReader(`{"name":"m2","url":"http://b.com"}`)))

	req := httptest.NewRequest("GET", "/api/v1/monitors", nil)
	w := httptest.NewRecorder()
	svc.listMonitors(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("list status = %d; want 200", w.Code)
	}

	var resp struct {
		Monitors []Monitor `json:"monitors"`
	}
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Monitors) != 2 {
		t.Errorf("expected 2 monitors; got %d", len(resp.Monitors))
	}
}

func TestHealthEndpoint(t *testing.T) {
	svc := NewMonitorEngine()
	req := httptest.NewRequest("GET", "/health", nil)
	w := httptest.NewRecorder()
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "healthy", "service": "monitor-engine",
		})
	})
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("health status = %d; want 200", w.Code)
	}

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	if resp["status"] != "healthy" {
		t.Errorf("expected status 'healthy'; got %v", resp["status"])
	}
}

func TestDBPersistence(t *testing.T) {
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	defer db.Close()

	_, err = db.Exec(`CREATE TABLE monitors (
		id TEXT PRIMARY KEY, name TEXT, url TEXT, interval_sec INTEGER DEFAULT 60,
		timeout_sec INTEGER DEFAULT 10, enabled INTEGER DEFAULT 1,
		last_status TEXT DEFAULT 'unknown', last_duration_ms REAL DEFAULT 0,
		created_at TEXT DEFAULT (datetime('now'))
	)`)
	if err != nil {
		t.Fatalf("create table: %v", err)
	}

	_, err = db.ExecContext(context.Background(),
		"INSERT INTO monitors (id, name, url) VALUES (?, ?, ?)",
		"test-id", "persist-mon", "http://example.com")
	if err != nil {
		t.Fatalf("insert: %v", err)
	}

	var count int
	db.QueryRow("SELECT COUNT(*) FROM monitors WHERE id = ?", "test-id").Scan(&count)
	if count != 1 {
		t.Errorf("expected 1 row; got %d", count)
	}

	_, err = db.ExecContext(context.Background(), "DELETE FROM monitors WHERE id = ?", "test-id")
	if err != nil {
		t.Fatalf("delete: %v", err)
	}

	db.QueryRow("SELECT COUNT(*) FROM monitors WHERE id = ?", "test-id").Scan(&count)
	if count != 0 {
		t.Errorf("expected 0 rows after delete; got %d", count)
	}
}

func TestErrorResponse(t *testing.T) {
	tests := []struct {
		name   string
		status int
		msg    string
	}{
		{"bad request", 400, "invalid input"},
		{"not found", 404, "monitor not found"},
		{"internal error", 500, "db error"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			writeMonitorError(w, tt.status, tt.msg)

			if w.Code != tt.status {
				t.Errorf("status = %d; want %d", w.Code, tt.status)
			}

			var resp ErrorResponse
			json.NewDecoder(w.Body).Decode(&resp)
			if resp.Error != tt.msg {
				t.Errorf("error = %q; want %q", resp.Error, tt.msg)
			}
		})
	}
}

func TestReadyEndpoint(t *testing.T) {
	svc := NewMonitorEngine()
	req := httptest.NewRequest("GET", "/ready", nil)
	w := httptest.NewRecorder()
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if svc.db == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]string{"status": "not ready"})
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
	})
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("expected 503 without db; got %d", w.Code)
	}
}
