package main

import (
	"testing"
	"time"
)

func TestRateLimiter(t *testing.T) {
	tests := []struct {
		name       string
		ratePerMin int
		burst      int
		key        string
		calls      int
		wantBlock  int
	}{
		{"burst allows burst requests then blocks", 60, 5, "user:1", 10, 5},
		{"single request always allowed", 60, 10, "user:2", 1, 0},
		{"different keys independent", 60, 3, "user:a", 6, 3},
		{"high burst allows many", 1000, 50, "user:b", 10, 0},
		{"minimal rate blocks quickly", 6, 2, "user:c", 5, 3},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rl := NewRateLimiter(tt.ratePerMin, tt.burst)
			defer rl.Stop()

			blocked := 0
			for i := 0; i < tt.calls; i++ {
				if !rl.Allow(tt.key) {
					blocked++
				}
			}
			if blocked != tt.wantBlock {
				t.Errorf("blocked %d requests; want %d (rate=%d, burst=%d, calls=%d)",
					blocked, tt.wantBlock, tt.ratePerMin, tt.burst, tt.calls)
			}
		})
	}
}

func TestRateLimiterRefill(t *testing.T) {
	rl := NewRateLimiter(120, 1) // 2 tokens/sec, burst=1
	defer rl.Stop()

	if !rl.Allow("key") {
		t.Error("expected first request allowed")
	}
	if rl.Allow("key") {
		t.Error("expected second request blocked (burst=1)")
	}

	time.Sleep(600 * time.Millisecond)

	if !rl.Allow("key") {
		t.Error("expected request allowed after refill")
	}
}

func TestRateLimiterSeparateKeys(t *testing.T) {
	rl := NewRateLimiter(60, 2)
	defer rl.Stop()

	rl.Allow("alice")
	rl.Allow("alice")
	if rl.Allow("alice") {
		t.Error("expected alice blocked after burst")
	}

	if !rl.Allow("bob") {
		t.Error("expected bob allowed (separate bucket)")
	}
	if !rl.Allow("bob") {
		t.Error("expected bob second request allowed (burst=2)")
	}
}

func TestRateLimiterCleanup(t *testing.T) {
	rl := NewRateLimiter(60, 5)
	defer rl.Stop()

	rl.Allow("old")
	rl.Allow("new")

	rl.mu.Lock()
	count := len(rl.buckets)
	rl.mu.Unlock()

	if count != 2 {
		t.Errorf("expected 2 buckets before cleanup, got %d", count)
	}
}

func TestRateLimiterConcurrency(t *testing.T) {
	rl := NewRateLimiter(1000, 100)
	defer rl.Stop()

	done := make(chan struct{})
	go func() {
		for i := 0; i < 50; i++ {
			rl.Allow("shared")
		}
		close(done)
	}()
	for i := 0; i < 50; i++ {
		rl.Allow("shared")
	}
	<-done

	rl.mu.RLock()
	b, ok := rl.buckets["shared"]
	rl.mu.RUnlock()
	if !ok {
		t.Error("expected bucket to exist")
	}
	if b.tokens < 0 {
		t.Errorf("expected non-negative tokens, got %f", b.tokens)
	}
}
