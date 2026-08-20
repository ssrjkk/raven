import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
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
      <PageHeader title="Code Sessions" subtitle="Session history and status" />
      <div className="space-y-2">
        {sessions.map((s) => (
          <div key={s.id} className="card p-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{s.goal}</div>
                <div className="text-xs text-tertiary">
                  {s.id.slice(0, 8)} · {s.project_path.slice(0, 50)} · {s.files} files
                </div>
              </div>
              <span className={s.status === "active" ? "badge badge-success" : "badge"}>
                {s.status}
              </span>
            </div>
          </div>
        ))}
        {sessions.length === 0 && <p className="empty-state">No coding sessions.</p>}
      </div>
    </div>
  );
}