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
    ["agent run", () => api.ideAgentRun("do the thing", "build", "/app")],
    ["video transcribe", () => api.mediaVideoTranscribe("clip.mp4")],
    ["github clone", () => api.githubCloneRepo("ssrjkk", "raven")],
  ])("gives %s the long timeout", async (_label, call) => {
    await call();
    expect(deadlines).toContain(LONG_REQUEST_TIMEOUT_MS);
  });
});
