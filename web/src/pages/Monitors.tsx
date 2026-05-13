import { useState, useEffect } from "react";
import { api, MonitorData } from "../api/client";

export default function Monitors() {
  const [monitors, setMonitors] = useState<MonitorData[]>([]);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setMonitors(await api.monitors()); } catch {}
  }

  async function toggle(action: string, id: string) {
    try {
      await api.monitorToggle(action, id);
      await load();
    } catch {}
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Monitors</h1>
      <div className="space-y-2">
        {monitors.map((m) => {
          const icons: Record<string, string> = { active: "🟢", paused: "⏸", error: "🔴" };
          return (
            <div key={m.id} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span>{icons[m.status] || "❓"}</span>
                  <div>
                    <div className="text-sm font-medium">{m.name}</div>
                    <div className="text-xs text-gray-500">
                      {m.id.slice(0, 8)} · {m.type} · {m.target.slice(0, 40)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">{m.interval_seconds}s</span>
                  {m.last_check && <span className="text-xs">{m.last_check.status === "up" ? "✅" : "❌"}</span>}
                  {m.status === "active" ? (
                    <button onClick={() => toggle("pause", m.id)}
                      className="text-xs text-yellow-400 hover:text-yellow-300 px-2 py-1 rounded hover:bg-yellow-900/20 transition">
                      Pause
                    </button>
                  ) : (
                    <button onClick={() => toggle("resume", m.id)}
                      className="text-xs text-green-400 hover:text-green-300 px-2 py-1 rounded hover:bg-green-900/20 transition">
                      Resume
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {monitors.length === 0 && <p className="text-sm text-gray-500 text-center py-8">No monitors configured.</p>}
      </div>
    </div>
  );
}
