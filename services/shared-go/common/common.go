package common

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
)

func EnvOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func ParseInt(s string, defaultVal int) int {
	if s == "" {
		return defaultVal
	}
	var v int
	if _, err := fmt.Sscanf(s, "%d", &v); err != nil {
		return defaultVal
	}
	return v
}

func SplitCSV(s string) []string {
	if s == "" {
		return nil
	}
	var result []string
	start := 0
	for i := 0; i <= len(s); i++ {
		if i == len(s) || s[i] == ',' {
			if i > start {
				result = append(result, s[start:i])
			}
			start = i + 1
		}
	}
	return result
}

type StatusWriter struct {
	http.ResponseWriter
	Status int
}

func (w *StatusWriter) WriteHeader(status int) {
	w.Status = status
	w.ResponseWriter.WriteHeader(status)
}

func WriteJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func ClientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		if idx := strings.IndexByte(fwd, ','); idx >= 0 {
			return strings.TrimSpace(fwd[:idx])
		}
		return strings.TrimSpace(fwd)
	}
	host := r.RemoteAddr
	if idx := strings.LastIndexByte(host, ':'); idx >= 0 {
		host = host[:idx]
	}
	return host
}
