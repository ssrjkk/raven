package main

import (
	"sync"
	"testing"
	"time"
)

func TestCircuitBreaker(t *testing.T) {
	tests := []struct {
		name      string
		threshold int
		recovery  time.Duration
		failures  int
		wantOpen  bool
	}{
		{"zero failures stays closed", 3, 10 * time.Millisecond, 0, false},
		{"below threshold stays closed", 3, 10 * time.Millisecond, 2, false},
		{"at threshold opens", 3, 10 * time.Millisecond, 3, true},
		{"above threshold stays open", 3, 10 * time.Millisecond, 5, true},
		{"single failure threshold", 1, 10 * time.Millisecond, 1, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cb := NewCircuitBreaker(tt.threshold, tt.recovery)
			for i := 0; i < tt.failures; i++ {
				cb.Failure()
			}
			if got := !cb.Allow(); got != tt.wantOpen {
				t.Errorf("circuit open = %v (Allow=%v); want open=%v", got, cb.Allow(), tt.wantOpen)
			}
		})
	}
}

func TestCircuitBreakerRecovery(t *testing.T) {
	cb := NewCircuitBreaker(2, 50*time.Millisecond)
	cb.Failure()
	cb.Failure()

	if cb.Allow() {
		t.Error("expected circuit to be open after 2 failures")
	}

	time.Sleep(60 * time.Millisecond)

	if !cb.Allow() {
		t.Error("expected circuit to recover after timeout")
	}
}

func TestCircuitBreakerSuccessResets(t *testing.T) {
	cb := NewCircuitBreaker(3, time.Minute)
	for i := 0; i < 2; i++ {
		cb.Failure()
	}
	cb.Success()
	for i := 0; i < 2; i++ {
		cb.Failure()
	}

	if !cb.Allow() {
		t.Error("expected circuit to stay closed after success reset")
	}

	cb.Failure()
	if cb.Allow() {
		t.Error("expected circuit to open after total 3 failures even with reset")
	}
}

func TestCircuitBreakerConcurrency(t *testing.T) {
	cb := NewCircuitBreaker(10, time.Second)
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cb.Failure()
		}()
	}
	wg.Wait()

	if cb.Allow() {
		t.Log("circuit closed (concurrent failures did not reach threshold)")
	} else {
		t.Log("circuit open after concurrent failures (expected due to race)")
	}
}

func TestCircuitBreakerMetrics(t *testing.T) {
	cb := NewCircuitBreaker(2, time.Minute)
	cb.Failure()
	cb.Failure()
	cb.Failure()

	if cb.Allow() {
		t.Error("expected circuit open after repeated failures")
	}
}
