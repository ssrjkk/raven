import { useState } from "react";
import { api } from "../api/client";
import type { DreamStatsData } from "../api/client";
import PageHeader from "../components/PageHeader";
import { SkeletonCard } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Dream() {
  const { data, isLoading, refetch } = useApiQuery<DreamStatsData | null>(["dreamStats"], () => api.dreamStats().catch(() => null), { refetchInterval: 5_000 });
  const [cycling, setCycling] = useState(false);
  const [cycleResult, setCycleResult] = useState<Record<string, number> | null>(null);

  const handleCycle = async () => {
    setCycling(true);
    setCycleResult(null);
    try {
      const res = await api.dreamCycle();
      setCycleResult(res.stats);
      await refetch();
    } catch {
      setCycleResult(null);
    } finally {
      setCycling(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Dream Engine" subtitle="Autonomous skill discovery from usage patterns" />
        <SkeletonCard height={120} />
        <SkeletonCard height={200} />
      </div>
    );
  }

  const d = data;
  const lastCycle = d?.last_cycle_time ? new Date(d.last_cycle_time * 1000).toLocaleString() : "—";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dream Engine"
        subtitle="Autonomous skill discovery from usage patterns"
        actions={
          <span className={`flex items-center gap-2 text-sm ${d?.running ? "text-success" : "text-danger"}`}>
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: d?.running ? "var(--dt-colors-status-success)" : "var(--dt-colors-status-error)" }} />
            {d?.running ? "Running" : "Stopped"}
          </span>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="stat-card">
          <div className="stat-card-label">Total Cycles</div>
          <div className="stat-card-value">{d?.total_cycles ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Last Cycle</div>
          <div className="text-sm font-bold mt-1.5 text-primary">{lastCycle}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Idle Timeout</div>
          <div className="stat-card-value">{d?.idle_timeout ?? 60}s</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">Cycle Interval</div>
          <div className="stat-card-value">{d?.cycle_interval ?? 300}s</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-secondary mb-3">Memory Tiers</h2>
          {d?.memory ? (
            <div className="space-y-2">
              {Object.entries(d.memory).map(([tier, count]) => (
                <div key={tier} className="flex items-center justify-between text-sm">
                  <span className="text-tertiary capitalize">{tier.replace("_", " ")}</span>
                  <span className="text-primary font-mono">{count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-tertiary">Memory stats unavailable</p>
          )}
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold text-secondary mb-3">Last Cycle Stats</h2>
          {d?.last_cycle_stats ? (
            <div className="space-y-2">
              {Object.entries(d.last_cycle_stats).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-sm">
                  <span className="text-tertiary capitalize">{k.replace(/_/g, " ")}</span>
                  <span className="text-primary font-mono">{String(v)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-tertiary">No cycles yet</p>
          )}
        </div>
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-secondary">Dream-Generated Skills</h2>
          <button
            onClick={handleCycle}
            disabled={cycling}
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent-muted text-accent"
          >
            {cycling ? "Running..." : "Trigger Cycle"}
          </button>
        </div>
        {cycleResult && (
          <div className="mb-3 p-3 rounded-lg text-sm bg-tertiary">
            <span className="text-success font-medium">Cycle complete:</span>{" "}
            {Object.entries(cycleResult).map(([k, v]) => `${k}: ${v}`).join(", ")}
          </div>
        )}
        {d?.skills && d.skills.length > 0 ? (
          <div className="space-y-2">
            {d.skills.map((skill) => (
              <div key={skill.name} className="flex items-center justify-between p-2 rounded-lg text-sm bg-tertiary">
                <div>
                  <span className="text-primary font-medium">{skill.name}</span>
                  <p className="text-tertiary text-xs mt-0.5">{skill.description}</p>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-muted text-accent">
                  {skill.source}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-tertiary">No dream-generated skills yet. Trigger a cycle to generate skills from patterns.</p>
        )}
      </div>
    </div>
  );
}