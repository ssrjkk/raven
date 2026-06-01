package main

import (
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

type CircuitBreaker struct {
	mu               sync.Mutex
	failures         int64
	lastFailureTime  time.Time
	threshold        int
	recoveryTimeout  time.Duration
	open             atomic.Bool
	trippedCounter   prometheus.Counter
}

func NewCircuitBreaker(threshold int, recoveryTimeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		threshold:       threshold,
		recoveryTimeout: recoveryTimeout,
		trippedCounter: promauto.NewCounter(prometheus.CounterOpts{
			Name: "circuit_breaker_tripped_total",
			Help: "Circuit breaker trips",
		}),
	}
}

func (cb *CircuitBreaker) Allow() bool {
	if !cb.open.Load() {
		return true
	}
	cb.mu.Lock()
	defer cb.mu.Unlock()
	if time.Since(cb.lastFailureTime) > cb.recoveryTimeout {
		cb.open.Store(false)
		atomic.StoreInt64(&cb.failures, 0)
		return true
	}
	return false
}

func (cb *CircuitBreaker) Success() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	atomic.StoreInt64(&cb.failures, 0)
}

func (cb *CircuitBreaker) Failure() {
	fails := atomic.AddInt64(&cb.failures, 1)
	if fails >= int64(cb.threshold) {
		if cb.open.CompareAndSwap(false, true) {
			cb.mu.Lock()
			cb.lastFailureTime = time.Now()
			cb.mu.Unlock()
			cb.trippedCounter.Inc()
		}
	}
}
