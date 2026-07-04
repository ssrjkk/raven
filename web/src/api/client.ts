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

export interface ChannelInfo {
  id: string;
  type: string;
  ready: boolean;
  stats: Record<string, number>;
}

export interface HealthCheck {
  name: string;
  ok: boolean;
  latency_ms: number;
  critical: boolean;
}

export interface HealthData {
  overall: boolean;
  checks: HealthCheck[];
}

export interface MetricsSnapshot {
  [key: string]: number;
}

export interface MonitorData {
  id: string;
  name: string;
  type: string;
  target: string;
  interval_seconds: number;
  status: string;
  last_check: { status: string; checked_at: number } | null;
}

export interface RoutineData {
  id: string;
  name: string;
  action: string;
  schedule: string;
  trigger: string;
  status: string;
  last_run_status: string | null;
}

export interface TaskData {
  id: string;
  goal: string;
  status: string;
  steps: { order: number; description: string; tool: string; status: string }[];
  created_at: number;
}

export interface CodingSessionData {
  id: string;
  goal: string;
  status: string;
  project_path: string;
  files: number;
}

export interface WsMessage {
  type: "message";
  role: string;
  content: string;
  session_id: string;
}

export interface AuthData {
  token: string;
  user: { id: string; role: string };
}

const BASE = "";

let _token: string | null = null;

export function getToken(): string | null {
  return _token;
}

export function setToken(token: string) {
  _token = token;
}

export function clearToken() {
  _token = null;
}

export function isAuthenticated(): boolean {
  return !!_token;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers,
      signal: controller.signal,
      ...init,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("Unauthorized");
    }
    if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  status: () => request<StatusData>("/api/status"),
  sessions: () => request<Session[]>("/api/sessions"),
  sessionMessages: (id: string) => request<MessageData[]>(`/api/messages/${id}`),
  createSession: () => request<{ id: string; channel: string }>("/api/sessions", { method: "POST" }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  agents: () => request<StatusData["agents"]>("/api/agents"),
  health: () => request<HealthData>("/api/health"),
  metrics: () => request<MetricsSnapshot>("/api/metrics"),
  channels: () => request<ChannelInfo[]>("/api/admin/channels"),
  systemStatus: () => request<{ channels: number; agents: number; running: boolean; version: string }>("/api/admin/system/status"),
  monitors: () => request<MonitorData[]>("/api/monitor/list"),
  monitorToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/monitor/${action}/${id}`, { method: "POST" }),
  routines: () => request<RoutineData[]>("/api/routine/list"),
  routineToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/routine/${action}/${id}`, { method: "POST" }),
  tasks: () => request<TaskData[]>("/api/task/list"),
  taskRun: (goal: string) => request<{ id: string }>("/api/task/run", { method: "POST", body: JSON.stringify({ goal }) }),
  taskCancel: (id: string) => request<{ ok: boolean }>(`/api/task/${id}/cancel`, { method: "POST" }),
  codeSessions: () => request<CodingSessionData[]>("/api/code/list"),
  config: () => request<Record<string, string>>("/api/admin/config"),
  shutdown: () => request<{ ok: boolean }>("/api/shutdown", { method: "POST" }),
  login: (username: string, password: string) =>
    request<AuthData>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<AuthData>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
};