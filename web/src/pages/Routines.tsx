import { useState, useEffect } from "react";
import { api, RoutineData } from "../api/client";
import { useToast } from "../components/Toast";

export default function Routines() {
  const [routines, setRoutines] = useState<RoutineData[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setRoutines(await api.routines());
    } catch (e) {
      console.error("Failed to load routines:", e);
      toast("Failed to load routines", "error");
    } finally {
      setLoading(false);
    }
  }

  async function toggle(action: string, id: string) {
    try {
      await api.routineToggle(action, id);
      toast(`Routine ${action}ed`, "success");
      await load();
    } catch (e) {
      console.error("Failed to toggle routine:", e);
      toast("Failed to toggle routine", "error");
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Routines</h1>
        <div className="space-y-2 animate-pulse">
          {[1, 2].map((i) => <div key={i} className="h-20 bg-gray-900/60 rounded-xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Routines</h1>
      <div className="space-y-2">
        {routines.map((r) => {
          const icons: Record<string, string> = { active: "🟢", paused: "⏸", error: "🔴" };
          return (
            <div key={r.id} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span>{icons[r.status] || "❓"}</span>
                  <div>
                    <div className="text-sm font-medium">{r.name}</div>
                    <div className="text-xs text-gray-500">
                      {r.id.slice(0, 8)} · {r.action} · {r.schedule}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {r.last_run_status && <span className="text-xs text-gray-500">last: {r.last_run_status}</span>}
                  {r.status === "active" ? (
                    <button onClick={() => toggle("pause", r.id)}
                      className="text-xs text-yellow-400 hover:text-yellow-300 px-2 py-1 rounded hover:bg-yellow-900/20 transition">
                      Pause
                    </button>
                  ) : (
                    <button onClick={() => toggle("resume", r.id)}
                      className="text-xs text-green-400 hover:text-green-300 px-2 py-1 rounded hover:bg-green-900/20 transition">
                      Resume
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {routines.length === 0 && <p className="text-sm text-gray-500 text-center py-8">No routines configured.</p>}
      </div>
    </div>
  );
}