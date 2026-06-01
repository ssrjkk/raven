package main

import (
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

type RateLimiter struct {
	mu       sync.Mutex
	clients  map[string]*tokenBucket
	rate     int
	burst    int
	stopCh   chan struct{}
	allowed  prometheus.Counter
	blocked  prometheus.Counter
}

type tokenBucket struct {
	tokens    float64
	lastCheck time.Time
}

func NewRateLimiter(rate, burst int) *RateLimiter {
	rl := &RateLimiter{
		clients: make(map[string]*tokenBucket),
		rate:    rate,
		burst:   burst,
		stopCh:  make(chan struct{}),
		allowed: promauto.NewCounter(prometheus.CounterOpts{
			Name: "rate_limiter_allowed_total", Help: "Allowed requests",
		}),
		blocked: promauto.NewCounter(prometheus.CounterOpts{
			Name: "rate_limiter_blocked_total", Help: "Blocked requests",
		}),
	}
	go rl.cleanup()
	return rl
}

func (rl *RateLimiter) Allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	bucket, ok := rl.clients[key]
	if !ok {
		bucket = &tokenBucket{tokens: float64(rl.burst), lastCheck: time.Now()}
		rl.clients[key] = bucket
	}

	now := time.Now()
	elapsed := now.Sub(bucket.lastCheck).Seconds()
	bucket.tokens += elapsed * float64(rl.rate) / 60.0
	if bucket.tokens > float64(rl.burst) {
		bucket.tokens = float64(rl.burst)
	}
	bucket.lastCheck = now

	if bucket.tokens >= 1 {
		bucket.tokens--
		rl.allowed.Inc()
		return true
	}
	rl.blocked.Inc()
	return false
}

func (rl *RateLimiter) cleanup() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			rl.mu.Lock()
			cutoff := time.Now().Add(-10 * time.Minute)
			for k, b := range rl.clients {
				if b.lastCheck.Before(cutoff) {
					delete(rl.clients, k)
				}
			}
			rl.mu.Unlock()
		case <-rl.stopCh:
			return
		}
	}
}

func (rl *RateLimiter) Stop() {
	close(rl.stopCh)
}
