import { api, type HealthData, type MetricsSnapshot, type StatusData } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";
import { useSessionEvents } from "../hooks/useSessionEvents";
import { Bot, Cpu, GitBranch, ListTodo, MessageSquare, Puzzle, Radio, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: status } = useApiQuery<StatusData | null>(["status"], () => api.status().catch((e: unknown) => { console.error("status load failed:", e); return null; }));
  const { data: health } = useApiQuery<HealthData | null>(["health"], () => api.health().catch((e: unknown) => { console.error("health load failed:", e); return null; }));
  const { data: metricsData } = useApiQuery<MetricsSnapshot>(["metrics"], () => api.metrics().catch((e: unknown) => { console.error("metrics load failed:", e); return {} as MetricsSnapshot; }));
  const { data: sys, isLoading } = useApiQuery<{ channels: number; agents: number; running: boolean; version: string } | null>(["systemStatus"], () => api.systemStatus().catch((e: unknown) => { console.error("system status load failed:", e); return null; }));
  const metrics = metricsData ?? ({} as MetricsSnapshot);
  const flowSessions = useSessionEvents();

  const quickActions = [
    { label: "Новый чат", icon: MessageSquare, to: "/chat" },
    { label: "Создать задачу", icon: ListTodo, to: "/tasks" },
    { label: "Git-статус", icon: GitBranch, to: "/git" },
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
            <div key={i} className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))", border: "1px solid var(--dt-colors-border-default)" }}>
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
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(600px 220px at 90% -20%, var(--dt-colors-accent-subtle, rgba(124, 58, 237, 0.14)), transparent 70%)",
          }}
        />
        <div className="relative flex flex-col md:flex-row md:items-center gap-5">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-1">
              <Sparkles size={17} className="shrink-0" style={{ color: "var(--dt-colors-accent-default)" }} />
              <h2 className="text-xl font-bold tracking-tight gradient-text">Welcome back</h2>
            </div>
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>
              Raven в сети
              {sys?.channels ? ` — активно каналов: ${sys.channels}` : ""}
              {status?.agents?.length ? `, агентов: ${status.agents.length}` : ""}
              {status?.plugins ? `, плагинов: ${status.plugins}` : ""}.
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
                className="w-7 h-7 rounded-lg flex items-center justify-center"
                style={{
                  backgroundColor: "var(--dt-colors-accent-muted)",
                  color: "var(--dt-colors-accent-default)",
                }}
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
            {health.checks.map((c) => (
              <div key={c.name} className="flex items-center justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <div className="flex items-center gap-2.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: c.ok ? "var(--dt-colors-status-success)" : "var(--dt-colors-status-error)" }} />
                  <span style={{ color: "var(--dt-colors-text-secondary)" }}>{c.name}</span>
                  {c.critical && <span className="badge badge-warning">critical</span>}
                </div>
                <span className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{c.latency_ms.toFixed(0)}ms</span>
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
              <div key={k} className="flex justify-between rounded-lg px-3 py-2" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <span style={{ color: "var(--dt-colors-text-tertiary)" }}>{k}</span>
                <span style={{ color: "var(--dt-colors-text-primary)" }} className="font-medium">{typeof v === "number" ? v.toLocaleString() : v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-semibold mb-3">Flow Sessions</h2>
        {flowSessions.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No active flow sessions yet.</p>
        ) : (
          <div className="space-y-2">
            {flowSessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <div className="flex items-center gap-2.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: s.status === "running" ? "var(--dt-colors-status-warning)" : "var(--dt-colors-status-success)" }} />
                  <span className="font-medium">{s.id}</span>
                  <span className="chip">{s.channel}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.status}</span>
                  <span className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.message_count} msgs</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
