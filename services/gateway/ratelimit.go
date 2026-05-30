package main

import (
	"net/http"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

type bucket struct {
	tokens   float64
	lastFill time.Time
}

type RateLimiter struct {
	mu       sync.RWMutex
	buckets  map[string]*bucket
	rate     float64
	burst    int
	interval time.Duration
	stopCh   chan struct{}

	allowedTotal prometheus.Counter
	blockedTotal prometheus.Counter
}

func NewRateLimiter(ratePerMin int, burst int) *RateLimiter {
	rl := &RateLimiter{
		buckets:  make(map[string]*bucket),
		rate:     float64(ratePerMin) / 60.0,
		burst:    burst,
		interval: time.Second,
		stopCh:   make(chan struct{}),
		allowedTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "rate_limiter_allowed_total",
			Help: "Total allowed requests",
		}),
		blockedTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "rate_limiter_blocked_total",
			Help: "Total blocked requests",
		}),
	}
	go rl.cleanup(5 * time.Minute)
	return rl
}

func (rl *RateLimiter) Stop() {
	close(rl.stopCh)
}

func (rl *RateLimiter) Allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	b, ok := rl.buckets[key]
	now := time.Now()
	if !ok {
		rl.buckets[key] = &bucket{tokens: float64(rl.burst) - 1, lastFill: now}
		rl.allowedTotal.Inc()
		return true
	}

	elapsed := now.Sub(b.lastFill).Seconds()
	b.tokens = min(float64(rl.burst), b.tokens+elapsed*rl.rate)
	b.lastFill = now

	if b.tokens < 1 {
		rl.blockedTotal.Inc()
		return false
	}
	b.tokens--
	rl.allowedTotal.Inc()
	return true
}

func (rl *RateLimiter) cleanup(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			rl.mu.Lock()
			now := time.Now()
			for key, b := range rl.buckets {
				if now.Sub(b.lastFill) > 10*time.Minute {
					delete(rl.buckets, key)
				}
			}
			rl.mu.Unlock()
		case <-rl.stopCh:
			return
		}
	}
}

func (g *Gateway) rateLimitMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key := r.RemoteAddr
		if userID, ok := r.Context().Value(contextUserID).(string); ok && userID != "" {
			key = "user:" + userID
		}
		if !g.rateLimiter.Allow(key) {
			w.Header().Set("Retry-After", "1")
			writeError(w, http.StatusTooManyRequests, ErrRateLimited, "rate limit exceeded")
			return
		}
		next.ServeHTTP(w, r)
	})
}
