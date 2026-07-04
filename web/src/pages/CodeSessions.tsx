import { useState, useEffect } from "react";
import { api, CodingSessionData } from "../api/client";
import { useToast } from "../components/Toast";

export default function CodeSessions() {
  const [sessions, setSessions] = useState<CodingSessionData[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      setSessions(await api.codeSessions());
    } catch (e) {
      console.error("Failed to load code sessions:", e);
      toast("Failed to load code sessions", "error");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Code Sessions</h1>
        <div className="space-y-2 animate-pulse">
          {[1, 2].map((i) => <div key={i} className="h-16 bg-gray-900/60 rounded-xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Code Sessions</h1>
      <div className="space-y-2">
        {sessions.map((s) => (
          <div key={s.id} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{s.goal}</div>
                <div className="text-xs text-gray-500">
                  {s.id.slice(0, 8)} · {s.project_path.slice(0, 50)} · {s.files} files
                </div>
              </div>
              <span className={`text-xs px-2 py-1 rounded ${
                s.status === "active" ? "bg-green-900/30 text-green-400" : "bg-gray-800/50 text-gray-500"
              }`}>{s.status}</span>
            </div>
          </div>
        ))}
        {sessions.length === 0 && <p className="text-sm text-gray-500 text-center py-8">No coding sessions.</p>}
      </div>
    </div>
  );
}