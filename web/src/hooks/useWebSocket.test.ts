import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { computeReconnectDelay, useWebSocket, WS_PENDING_LIMIT } from "./useWebSocket";

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

const sockets: FakeSocket[] = [];

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = FakeSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  constructor(public url: string) {
    sockets.push(this);
  }
  send(payload: string) {
    this.sent.push(payload);
  }
  close() {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.();
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
}

describe("useWebSocket outbound queue", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sockets.length = 0;
  });

  function mount() {
    sockets.length = 0;
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.spyOn(client, "getToken").mockReturnValue("tok-123");
    return renderHook(() => useWebSocket(() => {}));
  }

  it("flushes a message typed during the reconnect after the auth frame", () => {
    const { result } = mount();
    let accepted = false;
    act(() => {
      accepted = result.current.send("hello", "s1");
    });
    expect(accepted).toBe(true);
    expect(result.current.queued).toBe(1);
    expect(sockets[0].sent).toEqual([]);

    act(() => sockets[0].open());
    expect(result.current.queued).toBe(0);
    // The server reads the first frame as the credential when no query token is present, so a queued
    // message that jumped ahead of it would be answered with a 1008 close instead of a reply.
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: "auth", token: "tok-123" });
    expect(JSON.parse(sockets[0].sent[1])).toEqual({ text: "hello", session_id: "s1" });
  });

  it("refuses visibly instead of dropping when the queue is full", () => {
    const { result } = mount();
    const verdicts: boolean[] = [];
    act(() => {
      for (let i = 0; i < WS_PENDING_LIMIT + 2; i += 1) verdicts.push(result.current.send(`m${i}`, "s1"));
    });
    expect(verdicts.slice(WS_PENDING_LIMIT)).toEqual([false, false]);
    expect(result.current.queued).toBe(WS_PENDING_LIMIT);
  });

  it("sends straight away once the socket is open", () => {
    const { result } = mount();
    act(() => sockets[0].open());
    act(() => {
      result.current.send("now", "s1");
    });
    expect(result.current.queued).toBe(0);
    expect(sockets[0].sent).toHaveLength(2);
  });
});
