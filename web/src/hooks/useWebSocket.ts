import { useCallback, useEffect, useRef, useState } from "react";

import { getToken, WsMessage } from "../api/client";

type Handler = (msg: WsMessage) => void;

export function useWebSocket(onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;
  const reconnectAttempt = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

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
    };
    ws.onclose = () => {
      setConnected(false);
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempt.current), 30000);
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

  const send = useCallback((text: string, sessionId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ text, session_id: sessionId }));
    }
  }, []);

  return { connected, send };
}