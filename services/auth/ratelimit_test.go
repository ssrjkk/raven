package main

import (
	"sync"
	"testing"
	"time"
)

func TestAuthRateLimiter(t *testing.T) {
	tests := []struct {
		name       string
		rate       int
		burst      int
		key        string
		calls      int
		wantBlock  int
	}{
		{"burst allows burst then blocks", 60, 5, "1.2.3.4", 10, 5},
		{"single always allowed", 10, 3, "10.0.0.1", 1, 0},
		{"different keys independent", 120, 5, "user:alice", 8, 3},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rl := NewRateLimiter(tt.rate, tt.burst)
			defer rl.Stop()

			blocked := 0
			for i := 0; i < tt.calls; i++ {
				if !rl.Allow(tt.key) {
					blocked++
				}
			}
			if blocked != tt.wantBlock {
				t.Errorf("blocked %d; want %d", blocked, tt.wantBlock)
			}
		})
	}
}

func TestAuthRateLimiterRefill(t *testing.T) {
	rl := NewRateLimiter(120, 1) // 2/sec, burst=1
	defer rl.Stop()

	if !rl.Allow("key") {
		t.Error("expected first allowed")
	}
	if rl.Allow("key") {
		t.Error("expected second blocked")
	}

	time.Sleep(600 * time.Millisecond)

	if !rl.Allow("key") {
		t.Error("expected allowed after refill")
	}
}

func TestAuthRateLimiterConcurrency(t *testing.T) {
	rl := NewRateLimiter(1000, 100)
	defer rl.Stop()

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rl.Allow("conc")
		}()
	}
	wg.Wait()

	rl.mu.Lock()
	b, ok := rl.clients["conc"]
	rl.mu.Unlock()
	if !ok {
		t.Error("expected bucket to exist")
	}
	if b.tokens < 0 {
		t.Errorf("negative tokens: %f", b.tokens)
	}
}
