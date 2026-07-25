import { api } from "../api/client";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

export default function CodeSessions() {
  const { data: sessionsData, isLoading } = useApiQuery<import("../api/client").CodingSessionData[]>(["codeSessions"], () => api.codeSessions());
  const sessions = sessionsData ?? [];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={180} height={28} />
        {[1, 2, 3].map((i) => <SkeletonCard key={i} height={72} />)}
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