import { useCallback, useEffect, useRef, useState } from "react";

import { getToken } from "../api/client";

export interface AgentArtifact {
  artifact_id: string;
  title: string;
  type: string;
  file_path: string | null;
  content: string;
  step: number;
}

export interface AgentSocketEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface AgentRunOptions {
  maxSteps?: number;
  diffPreview?: boolean;
  proactiveScan?: boolean;
  maxToolRetries?: number;
}

function reconnectDelay(attempt: number, base = 1000, cap = 30000): number {
  return Math.min(base * Math.pow(2, attempt), cap);
}

// A reconnect takes up to 30s, and `send` used to return without a word when the socket was not OPEN:
// the operator pressed Run, the button did nothing, and `running` stayed false so the console looked
// idle. Outbound frames wait here instead, and the cap is what makes a full queue a visible refusal
// rather than the same silent drop one level down.
export const AGENT_PENDING_LIMIT = 32;

export function useAgentSocket(onEvent: (ev: AgentSocketEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);
  const pendingRef = useRef<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [queued, setQueued] = useState(0);

  const enqueue = useCallback((payload: string): boolean => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(payload);
      return true;
    }
    if (pendingRef.current.length >= AGENT_PENDING_LIMIT) return false;
    pendingRef.current.push(payload);
    setQueued(pendingRef.current.length);
    return true;
  }, []);

  const connect = useCallback(() => {
    const token = getToken();
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    const ws = new WebSocket(`${protocol}//${location.host}/aios/ws/agent${query}`);
    ws.onopen = () => {
      setConnected(true);
      attemptRef.current = 0;
      const waiting = pendingRef.current;
      pendingRef.current = [];
      setQueued(0);
      for (const payload of waiting) ws.send(payload);
    };
    ws.onclose = () => {
      setConnected(false);
      // A prompt still waiting for the reconnect is a run the operator asked for, not a finished one.
      if (pendingRef.current.length === 0) setRunning(false);
      if (!mountedRef.current) return;
      const delay = reconnectDelay(attemptRef.current);
      attemptRef.current += 1;
      timerRef.current = window.setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (!parsed || typeof parsed.type !== "string") return;
        if (parsed.type === "done" || parsed.type === "final") setRunning(false);
        handlerRef.current({
          type: parsed.type,
          data: (parsed.data ?? {}) as Record<string, unknown>,
          timestamp: typeof parsed.timestamp === "number" ? parsed.timestamp : Date.now(),
        });
      } catch (err) {
        console.error("agent socket malformed message:", err);
      }
    };
    wsRef.current = ws;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback(
    (prompt: string, opts?: AgentRunOptions): boolean => {
      const accepted = enqueue(
        JSON.stringify({
          prompt,
          max_steps: opts?.maxSteps ?? 30,
          diff_preview: opts?.diffPreview ?? true,
          proactive_scan: opts?.proactiveScan ?? true,
          max_tool_retries: opts?.maxToolRetries ?? 3,
        }),
      );
      if (accepted) setRunning(true);
      return accepted;
    },
    [enqueue],
  );

  const respond = useCallback(
    (payload: Record<string, unknown>): boolean => enqueue(JSON.stringify(payload)),
    [enqueue],
  );

  const cancel = useCallback((): boolean => {
    const accepted = enqueue(JSON.stringify({ type: "cancel" }));
    if (accepted) setRunning(false);
    return accepted;
  }, [enqueue]);

  return { connected, running, queued, send, respond, cancel };
}
