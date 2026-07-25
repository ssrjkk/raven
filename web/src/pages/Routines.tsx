import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type RoutineData } from "../api/client";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Routines() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: routines, isLoading } = useApiQuery<RoutineData[]>(["routines"], () => api.routines());

  const toggle = useMutation({
    mutationFn: ({ action, id }: { action: string; id: string }) => api.routineToggle(action, id),
    onSuccess: (_data, { action }) => {
      toast(`Routine ${action}ed`, "success");
      qc.invalidateQueries({ queryKey: ["routines"] });
    },
    onError: (_err, { action }) => {
      toast(`Failed to ${action} routine`, "error");
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
      <h1 className="text-2xl font-bold">Routines</h1>
      <div className="space-y-2">
        {routines?.map((r: RoutineData) => {
          const icons: Record<string, string> = { active: "🟢", paused: "⏸", error: "🔴" };
          return (
            <div key={r.id} className="flex items-center justify-between p-3 rounded-lg bg-secondary">
              <div>
                <div className="font-medium">{r.name}</div>
                <div className="text-xs text-tertiary">
                  {r.action} · every {r.schedule} · {r.trigger}
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span title={r.status}>{icons[r.status] || "⚪"}</span>
                {r.status === "active" ? (
                  <button onClick={() => toggle.mutate({ action: "pause", id: r.id })}
                    className="px-2 py-1 rounded text-xs font-medium" style={{ backgroundColor: "rgba(234,179,8,0.2)", color: "#eab308" }}>
                    Pause
                  </button>
                ) : (
                  <button onClick={() => toggle.mutate({ action: "resume", id: r.id })}
                    className="px-2 py-1 rounded text-xs font-medium" style={{ backgroundColor: "rgba(34,197,94,0.2)", color: "#22c55e" }}>
                    Resume
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {(!routines || routines.length === 0) && (
          <p className="text-sm text-tertiary">No routines configured.</p>
        )}
      </div>
    </div>
  );
}
