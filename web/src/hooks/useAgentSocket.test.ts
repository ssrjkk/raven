import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { AGENT_PENDING_LIMIT, useAgentSocket } from "./useAgentSocket";

const instances: FakeWebSocket[] = [];

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  constructor(public url: string) {
    instances.push(this);
  }
  send(payload: string) {
    this.sent.push(payload);
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

function mount() {
  instances.length = 0;
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.spyOn(client, "getToken").mockReturnValue("tok-123");
  return renderHook(() => useAgentSocket(() => {}));
}

describe("useAgentSocket outbound queue", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    instances.length = 0;
  });

  it("delivers a prompt the operator sent before the socket opened", () => {
    const { result } = mount();
    let accepted = false;
    act(() => {
      accepted = result.current.send("build the thing");
    });
    expect(accepted).toBe(true);
    expect(result.current.queued).toBe(1);
    expect(result.current.running).toBe(true);
    expect(instances[0].sent).toEqual([]);

    act(() => instances[0].open());
    expect(result.current.queued).toBe(0);
    expect(JSON.parse(instances[0].sent[0]).prompt).toBe("build the thing");
  });

  it("sends straight away once the socket is open", () => {
    const { result } = mount();
    act(() => instances[0].open());
    act(() => {
      result.current.send("now");
    });
    expect(result.current.queued).toBe(0);
    expect(instances[0].sent).toHaveLength(1);
  });

  it("refuses visibly instead of dropping when the queue is full", () => {
    const { result } = mount();
    const verdicts: boolean[] = [];
    act(() => {
      for (let i = 0; i < AGENT_PENDING_LIMIT + 3; i += 1) verdicts.push(result.current.send(`p${i}`));
    });
    expect(verdicts.slice(0, AGENT_PENDING_LIMIT)).toEqual(Array(AGENT_PENDING_LIMIT).fill(true));
    expect(verdicts.slice(AGENT_PENDING_LIMIT)).toEqual([false, false, false]);
    expect(result.current.queued).toBe(AGENT_PENDING_LIMIT);
  });

  it("keeps waiting frames across a reconnect and flushes them in order", () => {
    vi.useFakeTimers();
    const { result } = mount();
    act(() => {
      result.current.send("first");
    });
    act(() => instances[0].close());
    expect(result.current.running).toBe(true);
    act(() => {
      result.current.send("second");
    });
    expect(result.current.queued).toBe(2);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(instances).toHaveLength(2);
    act(() => instances[1].open());

    expect(result.current.queued).toBe(0);
    expect(instances[1].sent.map((raw) => JSON.parse(raw).prompt)).toEqual(["first", "second"]);
  });

  it("queues a confirmation reply and a cancel as well", () => {
    const { result } = mount();
    act(() => {
      result.current.respond({ type: "confirm", data: { approved: true } });
      result.current.cancel();
    });
    expect(result.current.queued).toBe(2);
    act(() => instances[0].open());
    expect(instances[0].sent.map((raw) => JSON.parse(raw).type)).toEqual(["confirm", "cancel"]);
  });

  it("still authenticates from the query string the gateway reads before accept", () => {
    mount();
    expect(instances[0].url).toContain("/aios/ws/agent?token=tok-123");
  });
});