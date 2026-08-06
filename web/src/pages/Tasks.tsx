import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

const statusBadge: Record<string, string> = {
  pending: "badge badge-warning", running: "badge badge-info", completed: "badge badge-success", failed: "badge badge-error", cancelled: "badge badge-accent",
};

export default function Tasks() {
  const qc = useQueryClient();
  const [goal, setGoal] = useState("");
  const { toast } = useToast();
  const { data: tasksData, isLoading } = useApiQuery<import("../api/client").TaskData[]>(["tasks"], () => api.tasks());
  const tasks = tasksData ?? [];

  const startTask = useMutation({
    mutationFn: (g: string) => api.taskRun(g),
    onSuccess: () => {
      setGoal("");
      toast("Task started", "success");
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: () => toast("Failed to start task", "error"),
  });

  const cancelTask = useMutation({
    mutationFn: (id: string) => api.taskCancel(id),
    onSuccess: () => {
      toast("Task cancelled", "info");
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: () => toast("Failed to cancel task", "error"),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton width={100} height={28} />
          <Skeleton width={120} height={36} rounded="md" />
        </div>
        {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Tasks" subtitle="Create and track autonomous task runs" />

      <form onSubmit={(e) => { e.preventDefault(); startTask.mutate(goal); }} className="flex gap-3">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Describe a task goal..."
          className="input-base flex-1"
        />
        <button type="submit" disabled={startTask.isPending} className="btn-primary">
          Run Task
        </button>
      </form>

      <div className="space-y-2">
        {tasks.map((t) => {
          const icons: Record<string, string> = { pending: "⏳", running: "🔄", completed: "✅", failed: "❌", cancelled: "🚫" };
          const done = t.steps.filter((s) => s.status === "completed").length;
          return (
            <div key={t.id} className="card p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{icons[t.status] || "❓"}</span>
                  <div>
                    <div className="text-sm font-medium">{t.goal}</div>
                    <div className="text-xs text-tertiary">
                      {t.id.slice(0, 8)} · {done}/{t.steps.length} steps
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`${statusBadge[t.status] || "badge badge-accent"}`}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "currentColor" }} />
                    {t.status}
                  </span>
                  {(t.status === "pending" || t.status === "running") && (
                    <button onClick={() => cancelTask.mutate(t.id)}
                      className="text-xs px-2 py-1 rounded transition text-danger hover:opacity-80">
                      Cancel
                    </button>
                  )}
                </div>
              </div>
              {t.steps.length > 0 && (
                <div className="mt-2 pl-8 space-y-0.5">
                  {t.steps.map((s) => (
                    <div key={s.order} className="flex items-center gap-2 text-xs text-tertiary">
                      <span>{s.status === "completed" ? "✅" : s.status === "failed" ? "❌" : "⏳"}</span>
                      <span>{s.description}</span>
                      <span className="text-tertiary">({s.tool})</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {tasks.length === 0 && <p className="text-sm text-tertiary text-center py-8">No tasks yet.</p>}
      </div>
    </div>
  );
}