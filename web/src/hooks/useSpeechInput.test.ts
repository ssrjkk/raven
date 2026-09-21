import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSpeechInput } from "./useSpeechInput";

interface FakeResult {
  isFinal: boolean;
  length: number;
  [index: number]: { transcript: string; confidence: number };
}

class FakeSpeechRecognition {
  static instances: FakeSpeechRecognition[] = [];
  continuous = false;
  interimResults = false;
  lang = "";
  maxAlternatives = 1;
  onresult: ((e: { resultIndex: number; results: FakeResult[] }) => void) | null = null;
  onerror: ((e: { error: string; message: string }) => void) | null = null;
  onend: (() => void) | null = null;
  onstart: (() => void) | null = null;
  started = false;
  start = vi.fn(() => {
    this.started = true;
  });
  stop = vi.fn(() => {
    this.started = false;
    this.onend?.();
  });
  abort = vi.fn();
  constructor() {
    FakeSpeechRecognition.instances.push(this);
  }
  emitResult(results: FakeResult[], resultIndex = 0) {
    this.onresult?.({ resultIndex, results });
  }
}

function result(transcript: string, isFinal: boolean): FakeResult {
  const r: FakeResult = { isFinal, length: 1 };
  r[0] = { transcript, confidence: 1 };
  return r;
}

describe("useSpeechInput", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeSpeechRecognition.instances = [];
  });

  it("reports unsupported when API is absent", () => {
    const { result: hook } = renderHook(() => useSpeechInput());
    expect(hook.current.supported).toBe(false);
    expect(FakeSpeechRecognition.instances).toHaveLength(0);
  });

  it("starts and stops listening", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { result: hook } = renderHook(() => useSpeechInput());
    expect(hook.current.supported).toBe(true);
    act(() => hook.current.start());
    expect(hook.current.listening).toBe(true);
    expect(FakeSpeechRecognition.instances[0].start).toHaveBeenCalled();
    act(() => hook.current.stop());
    expect(hook.current.listening).toBe(false);
  });

  it("accumulates final transcript and exposes interim", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { result: hook } = renderHook(() => useSpeechInput());
    act(() => hook.current.start());
    const rec = FakeSpeechRecognition.instances[0];
    act(() => rec.emitResult([result("hello", false)]));
    expect(hook.current.interim).toBe("hello");
    act(() => rec.emitResult([result("world", true)]));
    expect(hook.current.final).toBe("world");
    expect(hook.current.interim).toBe("");
  });

  it("appends successive final segments", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { result: hook } = renderHook(() => useSpeechInput());
    act(() => hook.current.start());
    const rec = FakeSpeechRecognition.instances[0];
    act(() => rec.emitResult([result("first", true)]));
    act(() => rec.emitResult([result("second", true)]));
    expect(hook.current.final).toBe("first second");
  });

  it("reset clears transcripts", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { result: hook } = renderHook(() => useSpeechInput());
    act(() => hook.current.start());
    const rec = FakeSpeechRecognition.instances[0];
    act(() => rec.emitResult([result("x", true)]));
    act(() => hook.current.reset());
    expect(hook.current.final).toBe("");
    expect(hook.current.error).toBeNull();
  });

  it("records error but ignores aborted/no-speech", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { result: hook } = renderHook(() => useSpeechInput());
    act(() => hook.current.start());
    const rec = FakeSpeechRecognition.instances[0];
    act(() => rec.onerror?.({ error: "no-speech", message: "" }));
    expect(hook.current.error).toBeNull();
    act(() => rec.onerror?.({ error: "not-allowed", message: "denied" }));
    expect(hook.current.error).toBe("not-allowed");
    expect(hook.current.listening).toBe(false);
  });

  it("aborts recognition on unmount", () => {
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    const { unmount } = renderHook(() => useSpeechInput());
    const rec = FakeSpeechRecognition.instances[0];
    unmount();
    expect(rec.abort).toHaveBeenCalled();
  });
});
