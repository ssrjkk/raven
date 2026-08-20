import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Pause, Play, Activity } from "lucide-react";

import { api, type RoutineData } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

const routineStatusIcon: Record<string, { icon: typeof Activity; color: string }> = {
  active: { icon: Activity, color: "var(--dt-colors-status-success)" },
  paused: { icon: Pause, color: "var(--dt-colors-status-warning)" },
  error: { icon: AlertCircle, color: "var(--dt-colors-status-error)" },
};

export default function Routines() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: routines, isLoading } = useApiQuery<RoutineData[]>(["routines"], () => api.routines());

  const toggle = useMutation({
    mutationFn: ({ action, id }: { action: string; id: string }) => api.routineToggle(action, id),
    onMutate: async ({ action, id }) => {
      await qc.cancelQueries({ queryKey: ["routines"] });
      const prev = qc.getQueryData<RoutineData[]>(["routines"]);
      qc.setQueryData<RoutineData[]>(["routines"], (old) =>
        (old ?? []).map((r) => (r.id === id ? { ...r, status: action === "pause" ? "paused" : "active" } : r)),
      );
      return { prev };
    },
    onSuccess: (_data, { action }) => {
      toast(`Routine ${action}ed`, "success");
      qc.invalidateQueries({ queryKey: ["routines"] });
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["routines"], ctx.prev);
      toast("Failed to update routine", "error");
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={120} height={28} />
        {[1, 2, 3].map((i) => <SkeletonCard key={i} height={80} />)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Routines" subtitle="Recurring routines executed on a schedule" />
      <div className="space-y-2">
        {routines?.map((r: RoutineData) => {
          const cfg = routineStatusIcon[r.status] ?? routineStatusIcon.error;
          const StatusIcon = cfg.icon;
          return (
            <div key={r.id} className="card flex items-center justify-between p-3">
              <div className="flex items-center gap-3">
                <span
                  className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}
                >
                  <StatusIcon size={16} style={{ color: cfg.color }} />
                </span>
                <div>
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-tertiary">
                    {r.action} · every {r.schedule} · {r.trigger}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span
                  className="text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: cfg.color }}
                >
                  {r.status}
                </span>
                {r.status === "active" ? (
                  <button onClick={() => toggle.mutate({ action: "pause", id: r.id })}
                    className="btn-soft px-2.5 py-1 text-xs" style={{ color: "var(--dt-colors-status-warning)", backgroundColor: "var(--dt-colors-status-warning-bg)" }}>
                    <Pause size={11} />
                    Pause
                  </button>
                ) : (
                  <button onClick={() => toggle.mutate({ action: "resume", id: r.id })}
                    className="btn-soft px-2.5 py-1 text-xs" style={{ color: "var(--dt-colors-status-success)", backgroundColor: "var(--dt-colors-status-success-bg)" }}>
                    <Play size={11} />
                    Resume
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {(!routines || routines.length === 0) && (
          <p className="empty-state">No routines configured yet.</p>
        )}
      </div>
    </div>
  );
}
