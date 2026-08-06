import { api, type HealthData, type MetricsSnapshot, type StatusData } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Dashboard() {
  const { data: status } = useApiQuery<StatusData | null>(["status"], () => api.status().catch((e: unknown) => { console.error("status load failed:", e); return null; }));
  const { data: health } = useApiQuery<HealthData | null>(["health"], () => api.health().catch((e: unknown) => { console.error("health load failed:", e); return null; }));
  const { data: metricsData } = useApiQuery<MetricsSnapshot>(["metrics"], () => api.metrics().catch((e: unknown) => { console.error("metrics load failed:", e); return {} as MetricsSnapshot; }));
  const { data: sys, isLoading } = useApiQuery<{ channels: number; agents: number; running: boolean; version: string } | null>(["systemStatus"], () => api.systemStatus().catch((e: unknown) => { console.error("system status load failed:", e); return null; }));
  const metrics = metricsData ?? ({} as MetricsSnapshot);

  const metricCards = [
    { label: "Channels", value: sys?.channels ?? status?.channels.length ?? "—" },
    { label: "Agents", value: sys?.agents ?? status?.agents.length ?? "—" },
    { label: "Plugins", value: status?.plugins ?? "—" },
    { label: "Model", value: status?.model?.split("/").pop() ?? "—" },
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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metricCards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className="stat-card-label">{c.label}</div>
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
                  <span className={`w-1.5 h-1.5 rounded-full ${c.ok ? "bg-green-400" : "bg-red-400"}`} />
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
    </div>
  );
}
