import { afterEach, describe, expect, it, vi } from "vitest";

import { computeReconnectDelay } from "./useWebSocket";

function stubRandom(value: number) {
  const spy = vi.spyOn(Math, "random").mockReturnValue(value);
  afterEach(() => spy.mockRestore());
}

describe("computeReconnectDelay", () => {
  it("grows exponentially from base", () => {
    stubRandom(0.5);
    expect(computeReconnectDelay(0)).toBeCloseTo(1000);
    expect(computeReconnectDelay(1)).toBeCloseTo(2000);
    expect(computeReconnectDelay(2)).toBeCloseTo(4000);
    expect(computeReconnectDelay(3)).toBeCloseTo(8000);
  });

  it("caps at 30 seconds", () => {
    stubRandom(0.5);
    expect(computeReconnectDelay(5)).toBe(30000);
    expect(computeReconnectDelay(10)).toBe(30000);
  });

  it("respects custom base and cap", () => {
    stubRandom(0.5);
    expect(computeReconnectDelay(1, 500, 3000)).toBeCloseTo(1000);
    expect(computeReconnectDelay(3, 500, 3000)).toBe(3000);
  });

  it("applies jitter within +/-30%", () => {
    const attempt = 4;
    const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);
    stubRandom(0);
    expect(computeReconnectDelay(attempt)).toBeCloseTo(baseDelay * 0.7);
    stubRandom(1);
    expect(computeReconnectDelay(attempt)).toBeCloseTo(baseDelay * 1.3);
  });

  it("never exceeds cap even with max jitter", () => {
    stubRandom(1);
    expect(computeReconnectDelay(10)).toBeLessThanOrEqual(30000);
  });
});
