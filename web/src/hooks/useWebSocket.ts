import { useEffect, useRef, useCallback, useState } from "react";
import { WsMessage } from "../api/client";

type Handler = (msg: WsMessage) => void;

export function useWebSocket(onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;
  const reconnectAttempt = useRef(0);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.onopen = () => {
      setConnected(true);
      reconnectAttempt.current = 0;
    };
    ws.onclose = () => {
      setConnected(false);
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempt.current), 30000);
      reconnectAttempt.current++;
      setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (!parsed || typeof parsed !== "object") return;
        if (typeof parsed.type !== "string" || typeof parsed.content !== "string") return;
        const msg: WsMessage = {
          type: parsed.type as WsMessage["type"],
          role: String(parsed.role ?? "assistant"),
          content: parsed.content.slice(0, 100000),
          session_id: String(parsed.session_id ?? ""),
        };
        handlerRef.current(msg);
      } catch { /* ignore malformed messages */ }
    };
    wsRef.current = ws;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
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