export interface Session {
  id: string;
  channel: string;
  user_id: string;
  agent_id: string;
  updated_at: string;
}

export interface MessageData {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
}

export interface StatusData {
  status: string;
  channels: string[];
  plugins: number;
  agents: { id: string; system_prompt: string; model: string | null }[];
  model: string;
}

export interface WsMessage {
  type: "message";
  role: string;
  content: string;
  session_id: string;
}

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json();
}

export const api = {
  status: () => request<StatusData>("/api/status"),
  sessions: () => request<Session[]>("/api/sessions"),
  sessionMessages: (id: string) => request<MessageData[]>(`/api/messages/${id}`),
  createSession: () => request<{ id: string; channel: string }>("/api/sessions", { method: "POST" }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  agents: () => request<StatusData["agents"]>("/api/agents"),
};
