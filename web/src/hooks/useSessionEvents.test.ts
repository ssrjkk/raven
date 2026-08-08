import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { useSessionEvents } from "./useSessionEvents";

function mockEventSource() {
  const instances: Array<{ url: string; onmessage: ((e: { data: string }) => void) | null; close: ReturnType<typeof vi.fn> }> = [];
  class FakeEventSource {
    url: string;
    onmessage: ((e: { data: string }) => void) | null = null;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close: ReturnType<typeof vi.fn>;
    constructor(url: string) {
      this.url = url;
      this.close = vi.fn();
      instances.push(this);
    }
  }
  const emit = (url: string, data: string) => {
    const inst = instances.find((i) => i.url === url);
    if (inst?.onmessage) inst.onmessage({ data });
  };
  return {
    fake: FakeEventSource,
    instances,
    emit,
  };
}

describe("useSessionEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does not connect without a token", () => {
    vi.stubGlobal("EventSource", class {});
    vi.spyOn(client, "getToken").mockReturnValue(null);
    const { result } = renderHook(() => useSessionEvents());
    expect(result.current).toEqual([]);
  });

  it("connects with token query param and adds sessions", () => {
    const env = mockEventSource();
    vi.stubGlobal("EventSource", env.fake);
    vi.spyOn(client, "getToken").mockReturnValue("tok-123");

    const { result } = renderHook(() => useSessionEvents());
    expect(env.instances.length).toBe(1);
    expect(env.instances[0].url).toBe("/events/sessions?token=tok-123");

    act(() => {
      env.emit(env.instances[0].url, JSON.stringify({ session: { id: "s1", channel: "test", created_at: "x", message_count: 3, status: "idle" } }));
    });
    expect(result.current).toHaveLength(1);
    expect(result.current[0].id).toBe("s1");
    expect(result.current[0].message_count).toBe(3);
  });

  it("upserts by id on subsequent events", () => {
    const env = mockEventSource();
    vi.stubGlobal("EventSource", env.fake);
    vi.spyOn(client, "getToken").mockReturnValue("tok-123");

    const { result } = renderHook(() => useSessionEvents());
    act(() => {
      env.emit(env.instances[0].url, JSON.stringify({ session: { id: "s1", channel: "test", created_at: "x", message_count: 1, status: "idle" } }));
      env.emit(env.instances[0].url, JSON.stringify({ session: { id: "s1", channel: "test", created_at: "x", message_count: 4, status: "running" } }));
    });
    expect(result.current).toHaveLength(1);
    expect(result.current[0].message_count).toBe(4);
    expect(result.current[0].status).toBe("running");
  });

  it("ignores malformed events", () => {
    const env = mockEventSource();
    vi.stubGlobal("EventSource", env.fake);
    vi.spyOn(client, "getToken").mockReturnValue("tok-123");

    const { result } = renderHook(() => useSessionEvents());
    act(() => {
      env.emit(env.instances[0].url, "not json");
      env.emit(env.instances[0].url, JSON.stringify({ foo: 1 }));
    });
    expect(result.current).toEqual([]);
  });

  it("closes the connection on unmount", () => {
    const env = mockEventSource();
    vi.stubGlobal("EventSource", env.fake);
    vi.spyOn(client, "getToken").mockReturnValue("tok-123");

    const { unmount } = renderHook(() => useSessionEvents());
    unmount();
    expect(env.instances[0].close).toHaveBeenCalledTimes(1);
  });
});
