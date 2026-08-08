import { useEffect, useRef, useState } from "react";

import { getToken } from "../api/client";

export interface FlowSessionInfo {
  id: string;
  channel: string;
  created_at: string;
  message_count: number;
  status: string;
}

export function useSessionEvents(): FlowSessionInfo[] {
  const [sessions, setSessions] = useState<FlowSessionInfo[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const es = new EventSource(`/events/sessions?token=${encodeURIComponent(token)}`);
    esRef.current = es;
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as { session?: FlowSessionInfo };
        const session = parsed?.session;
        if (!session || typeof session.id !== "string") return;
        setSessions((prev) => {
          const idx = prev.findIndex((s) => s.id === session.id);
          if (idx === -1) return [...prev, session];
          const next = [...prev];
          next[idx] = session;
          return next;
        });
      } catch (err) {
        console.error("SSE session event parse failed:", err);
      }
    };
    return () => {
      es.close();
      esRef.current = null;
    };
  }, []);

  return sessions;
}
