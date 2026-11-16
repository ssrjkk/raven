import { useCallback, useEffect, useRef, useState } from "react";

import { getToken, WsMessage } from "../api/client";

type Handler = (msg: WsMessage) => void;

export function computeReconnectDelay(attempt: number, base = 1000, cap = 30000): number {
  const exponential = Math.min(base * Math.pow(2, attempt), cap);
  const jitter = 0.7 + Math.random() * 0.6;
  return Math.min(exponential * jitter, cap);
}

// Same silent drop as the agent socket: a message typed during the up-to-30s reconnect window was
// discarded by `send` with no signal to the operator. Frames wait here; a full queue refuses visibly.
export const WS_PENDING_LIMIT = 32;

export function useWebSocket(onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [queued, setQueued] = useState(0);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;
  const reconnectAttempt = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const pendingRef = useRef<string[]>([]);

  const connect = useCallback(() => {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.onopen = () => {
      const token = getToken();
      if (token) {
        ws.send(JSON.stringify({ type: "auth", token }));
      }
      setConnected(true);
      reconnectAttempt.current = 0;
      // After the auth frame: the server reads the first frame as the credential.
      const waiting = pendingRef.current;
      pendingRef.current = [];
      setQueued(0);
      for (const payload of waiting) ws.send(payload);
    };
    ws.onclose = () => {
      setConnected(false);
      if (!mountedRef.current) return;
      const delay = computeReconnectDelay(reconnectAttempt.current);
      reconnectAttempt.current++;
      timerRef.current = setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (!parsed || typeof parsed !== "object") return;
        if (parsed.type === "agent_status") {
          handlerRef.current(parsed as WsMessage);
          return;
        }
        if (typeof parsed.type !== "string" || typeof parsed.content !== "string") return;
        const msg: WsMessage = {
          type: parsed.type as WsMessage["type"],
          role: String(parsed.role ?? "assistant"),
          content: parsed.content.slice(0, 100000),
          session_id: String(parsed.session_id ?? ""),
        };
        handlerRef.current(msg);
      } catch (e) { console.error("WS malformed message:", e, e instanceof Error ? e.message : String(e)); }
    };
    wsRef.current = ws;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((text: string, sessionId: string): boolean => {
    const payload = JSON.stringify({ text, session_id: sessionId });
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(payload);
      return true;
    }
    if (pendingRef.current.length >= WS_PENDING_LIMIT) return false;
    pendingRef.current.push(payload);
    setQueued(pendingRef.current.length);
    return true;
  }, []);

  return { connected, queued, send };
}