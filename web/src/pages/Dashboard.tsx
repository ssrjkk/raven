import { Bot, Cpu, GitBranch, ListTodo, MessageSquare, Puzzle, Radio, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api, type HealthData, type MetricsSnapshot, type StatusData, type SystemStatusData } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";
import { useSessionEvents } from "../hooks/useSessionEvents";

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: status } = useApiQuery<StatusData | null>(["status"], () => api.status().catch((e: unknown) => { console.error("status load failed:", e); return null; }));
  const { data: health } = useApiQuery<HealthData | null>(["health"], () => api.health().catch((e: unknown) => { console.error("health load failed:", e); return null; }));
  const { data: metricsData } = useApiQuery<MetricsSnapshot>(["metrics"], () => api.metrics().catch((e: unknown) => { console.error("metrics load failed:", e); return {} as MetricsSnapshot; }));
  const { data: sys, isLoading } = useApiQuery<SystemStatusData | null>(["systemStatus"], () => api.systemStatus().catch((e: unknown) => { console.error("system status load failed:", e); return null; }));
  const metrics = metricsData ?? ({} as MetricsSnapshot);
  const flowSessions = useSessionEvents();

  const quickActions = [
    { label: "New chat", icon: MessageSquare, to: "/chat" },
    { label: "Create a task", icon: ListTodo, to: "/tasks" },
    { label: "Git status", icon: GitBranch, to: "/git" },
  ];

  const metricCards = [
    { label: "Channels", value: sys?.channels ?? status?.channels.length ?? "—", icon: Radio },
    { label: "Agents", value: sys?.agents ?? status?.agents.length ?? "—", icon: Bot },
    { label: "Plugins", value: status?.plugins ?? "—", icon: Puzzle },
    { label: "Model", value: status?.model?.split("/").pop() ?? "—", icon: Cpu },
  ];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={180} height={28} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card-bordered p-4">
              <Skeleton width={60} height={12} rounded="md" />
              <Skeleton width={40} height={32} rounded="md" className="mt-2" />
            </div>
          ))}
        </div>
        <SkeletonCard height={120} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="System overview at a glance"
        actions={
          <span className={sys?.running ? "badge badge-success" : "badge badge-error"}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "currentColor" }} />
            {sys?.running ? "Running" : "Stopped"}
          </span>
        }
      />

      <div className="card relative overflow-hidden p-6">
        <div className="pointer-events-none absolute inset-0 card-wash" />
        <div className="relative flex flex-col md:flex-row md:items-center gap-5">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-1">
              <Sparkles size={17} className="shrink-0 text-accent" />
              <h2 className="text-xl font-bold tracking-tight gradient-text">Welcome back</h2>
            </div>
            <p className="text-sm text-tertiary">
              Raven is online
              {sys?.channels ? ` — active channels: ${sys.channels}` : ""}
              {status?.agents?.length ? `, agents: ${status.agents.length}` : ""}
              {status?.plugins ? `, plugins: ${status.plugins}` : ""}.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {quickActions.map(({ label, icon: Icon, to }) => (
              <button key={to} onClick={() => navigate(to)} className="btn-outline px-3.5 py-2 text-xs">
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metricCards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className="flex items-center justify-between">
              <div className="stat-card-label">{c.label}</div>
              <span
                className="w-7 h-7 rounded-lg flex items-center justify-center bg-accent-muted text-accent"

              >
                <c.icon size={15} />
              </span>
            </div>
            <div className="stat-card-value">{String(c.value)}</div>
          </div>
        ))}
      </div>

      {health && (
        <div className="card">
          <h2 className="text-sm font-semibold mb-3">Health Checks</h2>
          <div className="space-y-2">
            {Object.entries(health.checks).map(([name, c]) => (
              <div key={name} className="flex items-center justify-between text-sm rounded-lg px-3 py-2 bg-tertiary">
                <div className="flex items-center gap-2.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${c.ok ? "dot-success" : "dot-error"}`} />
                  <span className="text-secondary">{name}</span>
                </div>
                <span className="text-xs text-tertiary">{c.detail || (c.ok ? "ok" : "failed")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card">
          <h2 className="text-sm font-semibold mb-3">Channels</h2>
          <div className="flex flex-wrap gap-2">
            {(status?.channels ?? []).map((ch) => (
              <span key={ch} className="chip">{ch}</span>
            ))}
          </div>
        </div>
        <div className="card">
          <h2 className="text-sm font-semibold mb-3">Key Metrics</h2>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(metrics).slice(0, 8).map(([k, v]) => (
              <div key={k} className="flex justify-between rounded-lg px-3 py-2 bg-tertiary">
                <span className="text-tertiary">{k}</span>
                <span className="font-medium text-primary">{typeof v === "number" ? v.toLocaleString() : v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-semibold mb-3">Flow Sessions</h2>
        {flowSessions.length === 0 ? (
          <p className="text-sm text-tertiary">No active flow sessions yet.</p>
        ) : (
          <div className="space-y-2">
            {flowSessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between text-sm rounded-lg px-3 py-2 bg-tertiary">
                <div className="flex items-center gap-2.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${s.status === "running" ? "dot-warning" : "dot-success"}`} />
                  <span className="font-medium">{s.id}</span>
                  <span className="chip">{s.channel}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-tertiary">{s.status}</span>
                  <span className="text-xs text-tertiary">{s.message_count} msgs</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
