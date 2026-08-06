import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Monitors() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: monitorsData, isLoading } = useApiQuery<import("../api/client").MonitorData[]>(["monitors"], () => api.monitors());
  const monitors = monitorsData ?? [];

  const toggle = useMutation({
    mutationFn: ({ action, id }: { action: string; id: string }) => api.monitorToggle(action, id),
    onSuccess: (_data, { action }) => {
      toast(`Monitor ${action}ed`, "success");
      qc.invalidateQueries({ queryKey: ["monitors"] });
    },
    onError: (_err, { action }) => {
      toast(`Failed to ${action} monitor`, "error");
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={140} height={28} />
        {[1, 2, 3].map((i) => <SkeletonCard key={i} height={80} />)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Monitors" subtitle="Health checks for your services" />
      <div className="space-y-2">
        {monitors.map((m) => {
          const icons: Record<string, string> = { active: "🟢", paused: "⏸", error: "🔴" };
          return (
            <div key={m.id} className="card">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span>{icons[m.status] || "❓"}</span>
                  <div>
                    <div className="text-sm font-medium">{m.name}</div>
                    <div className="text-xs text-tertiary">
                      {m.id.slice(0, 8)} · {m.type} · {m.target.slice(0, 40)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-tertiary">{m.interval_seconds}s</span>
                  {m.last_check && <span className="text-xs">{m.last_check.status === "up" ? "✅" : "❌"}</span>}
                    {m.status === "active" ? (
                    <button onClick={() => toggle.mutate({ action: "pause", id: m.id })}
                      className="px-2 py-1 rounded text-xs font-medium transition hover:brightness-125"
                      style={{ color: "var(--dt-colors-status-warning)", backgroundColor: "var(--dt-colors-status-warning-bg)" }}>
                      Pause
                    </button>
                  ) : (
                    <button onClick={() => toggle.mutate({ action: "resume", id: m.id })}
                      className="px-2 py-1 rounded text-xs font-medium transition hover:brightness-125"
                      style={{ color: "var(--dt-colors-status-success)", backgroundColor: "var(--dt-colors-status-success-bg)" }}>
                      Resume
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {monitors.length === 0 && <p className="text-sm text-tertiary text-center py-8">No monitors configured.</p>}
      </div>
    </div>
  );
}