import { useState, useEffect } from "react";
import { api, TaskData } from "../api/client";
import { useToast } from "../components/Toast";

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [pageLoading, setPageLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setTasks(await api.tasks());
    } catch (e) {
      console.error("Failed to load tasks:", e);
      toast("Failed to load tasks", "error");
    } finally {
      setPageLoading(false);
    }
  }

  async function runTask() {
    if (!goal.trim()) return;
    setLoading(true);
    try {
      await api.taskRun(goal);
      setGoal("");
      toast("Task started", "success");
      await load();
    } catch (e) {
      console.error("Failed to start task:", e);
      toast("Failed to start task", "error");
    }
    setLoading(false);
  }

  async function cancelTask(id: string) {
    try {
      await api.taskCancel(id);
      toast("Task cancelled", "info");
      await load();
    } catch (e) {
      console.error("Failed to cancel task:", e);
      toast("Failed to cancel task", "error");
    }
  }

  if (pageLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Tasks</h1>
        <div className="space-y-2 animate-pulse">
          {[1, 2].map((i) => <div key={i} className="h-24 bg-gray-900/60 rounded-xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Tasks</h1>

      <form onSubmit={(e) => { e.preventDefault(); runTask(); }} className="flex gap-3">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Describe a task goal..."
          className="flex-1 bg-gray-800/60 border border-gray-700/50 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-violet-500/50"
        />
        <button type="submit" disabled={loading}
          className="bg-violet-600 hover:bg-violet-500 disabled:bg-violet-800/50 text-white px-5 py-2 rounded-xl text-sm font-medium transition">
          Run Task
        </button>
      </form>

      <div className="space-y-2">
        {tasks.map((t) => {
          const icons: Record<string, string> = { pending: "⏳", running: "🔄", completed: "✅", failed: "❌", cancelled: "🚫" };
          const done = t.steps.filter((s) => s.status === "completed").length;
          return (
            <div key={t.id} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{icons[t.status] || "❓"}</span>
                  <div>
                    <div className="text-sm font-medium">{t.goal}</div>
                    <div className="text-xs text-gray-500">
                      {t.id.slice(0, 8)} · {done}/{t.steps.length} steps
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">{t.status}</span>
                  {(t.status === "pending" || t.status === "running") && (
                    <button onClick={() => cancelTask(t.id)}
                      className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-900/20 transition">
                      Cancel
                    </button>
                  )}
                </div>
              </div>
              {t.steps.length > 0 && (
                <div className="mt-2 pl-8 space-y-0.5">
                  {t.steps.map((s) => (
                    <div key={s.order} className="flex items-center gap-2 text-xs text-gray-500">
                      <span>{s.status === "completed" ? "✅" : s.status === "failed" ? "❌" : "⏳"}</span>
                      <span>{s.description}</span>
                      <span className="text-gray-600">({s.tool})</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {tasks.length === 0 && <p className="text-sm text-gray-500 text-center py-8">No tasks yet.</p>}
      </div>
    </div>
  );
}