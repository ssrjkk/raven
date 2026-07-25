import { api, type HealthData, type MetricsSnapshot, type StatusData } from "../api/client";
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <span className={`flex items-center gap-2 text-sm ${sys?.running ? "text-green-400" : "text-red-400"}`}>
          <span className={`w-2 h-2 rounded-full ${sys?.running ? "bg-green-400" : "bg-red-400"}`} />
          {sys?.running ? "Running" : "Stopped"}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metricCards.map((c) => (
          <div key={c.label} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider">{c.label}</div>
            <div className="text-2xl font-bold mt-1">{String(c.value)}</div>
          </div>
        ))}
      </div>

      {health && (
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Health Checks</h2>
          <div className="space-y-2">
            {health.checks.map((c) => (
              <div key={c.name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${c.ok ? "bg-green-400" : "bg-red-400"}`} />
                  <span className="text-gray-400">{c.name}</span>
                  {c.critical && <span className="text-[10px] text-yellow-500">critical</span>}
                </div>
                <span className="text-gray-500">{c.latency_ms.toFixed(0)}ms</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Channels</h2>
          <div className="flex flex-wrap gap-2">
            {(status?.channels ?? []).map((ch) => (
              <span key={ch} className="px-2.5 py-1 bg-gray-800/60 rounded-lg text-xs text-gray-300">{ch}</span>
            ))}
          </div>
        </div>
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Key Metrics</h2>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(metrics).slice(0, 8).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-gray-500">{k}</span>
                <span className="text-gray-200">{typeof v === "number" ? v.toLocaleString() : v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}