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

export function useAgentSocket(onEvent: (ev: AgentSocketEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);

  const connect = useCallback(() => {
    const token = getToken();
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    const ws = new WebSocket(`${protocol}//${location.host}/ws/agent${query}`);
    ws.onopen = () => {
      setConnected(true);
      attemptRef.current = 0;
    };
    ws.onclose = () => {
      setConnected(false);
      setRunning(false);
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
        if (parsed.type === "done") setRunning(false);
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

  const send = useCallback((prompt: string, opts?: AgentRunOptions) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    setRunning(true);
    wsRef.current.send(
      JSON.stringify({
        prompt,
        max_steps: opts?.maxSteps ?? 30,
        diff_preview: opts?.diffPreview ?? true,
        proactive_scan: opts?.proactiveScan ?? true,
        max_tool_retries: opts?.maxToolRetries ?? 3,
      }),
    );
  }, []);

  return { connected, running, send };
}
