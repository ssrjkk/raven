import { useEffect, useRef, useCallback, useState } from "react";
import { WsMessage } from "../api/client";

type Handler = (msg: WsMessage) => void;

export function useWebSocket(onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  const connect = useCallback(() => {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as WsMessage;
        handlerRef.current(data);
      } catch { /* ignore */ }
    };
    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  const send = useCallback((text: string, sessionId: string) => {
    wsRef.current?.send(JSON.stringify({ text, session_id: sessionId }));
  }, []);

  return { connected, send };
}
