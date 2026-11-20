import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, LONG_REQUEST_TIMEOUT_MS, request } from "./client";

function okResponse(body: unknown = { ok: true }) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("request abort deadlines", () => {
  let deadlines: number[] = [];
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    deadlines = [];
    const realSetTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler, ms?: number, ...args: unknown[]) => {
      if (typeof ms === "number") deadlines.push(ms);
      return realSetTimeout(handler, 0, ...args);
    }) as typeof window.setTimeout);
    fetchMock = vi.fn(async () => okResponse());
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("aborts an ordinary call at 15 seconds", async () => {
    await request<{ ok: boolean }>("/api/status");
    expect(deadlines).toContain(15000);
  });

  it("does not abort a server-side chaos experiment at 15 seconds", async () => {
    await api.chaosRunExperiment("nightly", '[{"fault_type":"cpu_storm"}]');
    expect(deadlines).toContain(LONG_REQUEST_TIMEOUT_MS);
    expect(deadlines).not.toContain(15000);
  });

  it.each([
    ["tests run", () => api.testsRun("tests/", "unit")],
    ["fine-tune", () => api.finetuneStartTraining()],
    ["video transcribe", () => api.mediaVideoTranscribe("clip.mp4")],
    ["github clone", () => api.githubCloneRepo("ssrjkk", "raven")],
  ])("gives %s the long timeout", async (_label, call) => {
    await call();
    expect(deadlines).toContain(LONG_REQUEST_TIMEOUT_MS);
  });
});

describe("a request the gateway refused for budget", () => {
  let answers: Response[];
  let fetchMock: ReturnType<typeof vi.fn>;
  let waits: number[];

  function refused(retryAfter: string | null): Response {
    const body = retryAfter === null ? { error: "Too many requests" } : { error: "Too many requests", retry_after: Number(retryAfter) };
    return new Response(JSON.stringify(body), {
      status: 429,
      headers: retryAfter === null ? {} : { "retry-after": retryAfter },
    });
  }

  beforeEach(() => {
    answers = [];
    waits = [];
    const realSetTimeout = window.setTimeout.bind(window);
    // The retry sleeps for the seconds the header named; the test runs the timer immediately and records
    // the duration it was asked for, which is the promise being checked.
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler, ms?: number, ...args: unknown[]) => {
      if (typeof ms === "number" && ms > 0 && ms !== 15000) waits.push(ms);
      return realSetTimeout(handler, 0, ...args);
    }) as typeof window.setTimeout);
    fetchMock = vi.fn(async () => answers.shift() ?? refused(null));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("comes back when Retry-After said the budget would refill", async () => {
    answers.push(refused("2"), okResponse({ ok: true }));
    await expect(request<{ ok: boolean }>("/api/monitor/list")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(waits).toContain(2000);
  });

  it("refuses once and reports the wait instead of sitting out the window", async () => {
    answers.push(refused("60"), okResponse({ ok: true }));
    await expect(request<{ ok: boolean }>("/api/monitor/list")).rejects.toThrow(/429 rate limited, retry in 60s/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(waits).toEqual([]);
  });

  it("keeps the one retry it promised when the slot is taken by then", async () => {
    answers.push(refused("2"), refused("1"));
    await expect(request<{ ok: boolean }>("/api/monitor/list")).rejects.toThrow(/429 rate limited, retry in 1s/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports the wait the refusal that ended the request actually named", async () => {
    answers.push(refused("2"), refused(null));
    await expect(request<{ ok: boolean }>("/api/monitor/list")).rejects.toThrow(/^API \/api\/monitor\/list: 429 rate limited$/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports a refusal that named no wait without inventing one", async () => {
    answers.push(refused(null), okResponse({ ok: true }));
    await expect(request<{ ok: boolean }>("/api/monitor/list")).rejects.toThrow(/429 rate limited/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(waits).toEqual([]);
  });
});
