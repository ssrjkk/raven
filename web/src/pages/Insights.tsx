import { useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

interface CodingInsights {
  total_commits: number;
  total_days_active: number;
  avg_commits_per_day: number;
  commits_per_day: { date: string; count: number }[];
  peak_hours: { hour: number; count: number }[];
  top_files: { path: string; changes: number }[];
  error?: string;
}

interface LlmInsights {
  total_calls: number;
  total_cost: number;
  total_tokens: number;
  avg_cost_per_call: number;
  calls_per_day: { date: string; calls: number; cost: number; tokens: number }[];
  models: { model: string; calls: number }[];
  peak_hours: { hour: number; calls: number }[];
}

interface WorkspaceInsights {
  total_files: number;
  total_dirs: number;
  by_extension: Record<string, number>;
  largest_files: { path: string; size_bytes: number }[];
  recently_modified: { path: string; modified_at: string }[];
}

export default function Insights() {
  const [tab, setTab] = useState<"coding" | "llm" | "workspace">("coding");
  const [error, setError] = useState("");
  const [days, setDays] = useState(30);

  const { data: coding, isLoading: loading } = useApiQuery<CodingInsights>(["insightsCoding", String(days)], () => api.insightsCoding(days).catch((err) => { setError(err instanceof Error ? err.message : "Failed to load insights"); throw err; }));
  const { data: llm } = useApiQuery<LlmInsights>(["insightsLlm", String(days)], () => api.insightsLlm(days));
  const { data: workspace } = useApiQuery<WorkspaceInsights>(["insightsWorkspace"], () => api.insightsWorkspace());

  return (
    <div>
      <PageHeader
        title="Developer Insights"
        subtitle="Coding, LLM usage, and workspace analytics"
        actions={
          <div className="flex items-center gap-2">
            <label className="text-xs text-tertiary">Period (days):</label>
            <select value={days} onChange={e => setDays(Number(e.target.value))}
              className="input-base" style={{ width: "auto" }}>
              {[7, 14, 30, 60, 90, 180, 365].map(d => <option key={d} value={d}>{d}d</option>)}
            </select>
          </div>
        }
      />

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}

      <div className="flex gap-1 mb-6 p-1 rounded-lg bg-tertiary">
        {(["coding", "llm", "workspace"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="px-4 py-1.5 rounded-md text-sm font-medium capitalize transition-all"
            style={{
              backgroundColor: tab === t ? "var(--dt-colors-accent-default)" : "transparent",
              color: tab === t ? "#fff" : "var(--dt-colors-text-secondary)",
            }}>
            {t === "llm" ? "LLM Usage" : t === "workspace" ? "Workspace" : "Coding Activity"}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-4">
          <SkeletonCard count={3} />
        </div>
      ) : (
        <>
          {tab === "coding" && <CodingInsights data={coding ?? null} />}
          {tab === "llm" && <LLMInsights data={llm ?? null} />}
          {tab === "workspace" && <WorkspaceInsights data={workspace ?? null} />}
        </>
      )}
    </div>
  );
}

function CodingInsights({ data }: { data: CodingInsights | null }) {
  if (!data) return <EmptyState />;
  if (data.error) return <EmptyState message={data.error} />;

  const maxCommit = Math.max(...(data.commits_per_day?.map((d) => d.count) || [1]), 1);
  const maxHour = Math.max(...(data.peak_hours?.map((h) => h.count) || [1]), 1);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total Commits" value={data.total_commits} />
        <StatCard label="Active Days" value={data.total_days_active} />
        <StatCard label="Avg / Day" value={data.avg_commits_per_day} />
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3">Commits per Day</h3>
        <div className="flex items-end gap-1 h-32">
          {(data.commits_per_day || []).slice(-30).map((d) => (
            <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full rounded-t transition-all duration-200" style={{
                height: `${(d.count / maxCommit) * 100}%`,
                minHeight: d.count > 0 ? 4 : 0,
                backgroundColor: "var(--dt-colors-accent-default)",
                opacity: 0.7 + (d.count / maxCommit) * 0.3,
              }} title={`${d.date}: ${d.count} commits`} />
              <span className="text-[9px] text-tertiary">
                {d.date.slice(5)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Peak Coding Hours</h3>
          <div className="flex items-end gap-1 h-24">
            {Array.from({ length: 24 }, (_, i) => {
              const h = data.peak_hours?.find((ph) => ph.hour === i);
              const count = h?.count || 0;
              return (
                <div key={i} className="flex-1 flex flex-col items-center">
                  <div className="w-full rounded-t transition-all" style={{
                    height: `${(count / maxHour) * 100}%`,
                    minHeight: count > 0 ? 2 : 0,
                    backgroundColor: "var(--dt-colors-accent-default)",
                    opacity: 0.4 + (count / maxHour) * 0.6,
                  }} title={`${i}:00 — ${count} commits`} />
                  <span className="text-[8px] mt-0.5 text-tertiary">{i}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Most Changed Files</h3>
          {(!data.top_files || data.top_files.length === 0) ? (
            <p className="text-sm text-tertiary">No data.</p>
          ) : (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {data.top_files.map((f) => (
                <div key={f.path} className="flex justify-between text-xs py-0.5">
                  <span className="truncate flex-1 font-mono text-secondary">{f.path}</span>
                  <span className="ml-2 shrink-0 text-tertiary">{f.changes} chg</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LLMInsights({ data }: { data: LlmInsights | null }) {
  if (!data) return <EmptyState />;

  const maxCalls = Math.max(...(data.calls_per_day?.map((d) => d.calls) || [1]), 1);
  const maxModel = Math.max(...(data.models?.map((m) => m.calls) || [1]), 1);
  const maxHour = Math.max(...(data.peak_hours?.map((h) => h.calls) || [1]), 1);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Calls" value={data.total_calls} />
        <StatCard label="Total Cost" value={`$${data.total_cost?.toFixed(4)}`} />
        <StatCard label="Total Tokens" value={data.total_tokens?.toLocaleString()} />
        <StatCard label="Avg Cost/Call" value={`$${data.avg_cost_per_call?.toFixed(6)}`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">LLM Calls per Day</h3>
          <div className="flex items-end gap-1 h-28">
            {(data.calls_per_day || []).slice(-30).map((d) => (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                <div className="w-full rounded-t transition-all" style={{
                  height: `${(d.calls / maxCalls) * 100}%`,
                  minHeight: d.calls > 0 ? 2 : 0,
                  backgroundColor: "var(--dt-colors-accent-default)",
                  opacity: 0.6 + (d.calls / maxCalls) * 0.4,
                }} />
                <span className="text-[9px] text-tertiary">{d.date.slice(5)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Models Used</h3>
          <div className="space-y-2">
            {(data.models || []).map((m) => (
              <div key={m.model} className="flex items-center gap-2">
                <span className="text-xs font-mono w-32 truncate text-secondary">{m.model}</span>
                <div className="flex-1 h-4 rounded bg-primary">
                  <div className="h-full rounded transition-all" style={{
                    width: `${(m.calls / maxModel) * 100}%`,
                    backgroundColor: "var(--dt-colors-accent-default)",
                  }} />
                </div>
                <span className="text-xs shrink-0 text-tertiary">{m.calls}</span>
              </div>
            ))}
            {(!data.models || data.models.length === 0) && (
              <p className="text-sm text-tertiary">No data.</p>
            )}
          </div>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3">Peak LLM Usage Hours</h3>
        <div className="flex items-end gap-1 h-24">
          {Array.from({ length: 24 }, (_, i) => {
            const h = data.peak_hours?.find((ph) => ph.hour === i);
            const count = h?.calls || 0;
            return (
              <div key={i} className="flex-1 flex flex-col items-center">
                <div className="w-full rounded-t" style={{
                  height: `${(count / maxHour) * 100}%`,
                  minHeight: count > 0 ? 2 : 0,
                  backgroundColor: "var(--dt-colors-accent-default)",
                  opacity: 0.3 + (count / maxHour) * 0.7,
                }} />
                <span className="text-[8px] mt-0.5 text-tertiary">{i}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function WorkspaceInsights({ data }: { data: { total_files: number; total_dirs: number; by_extension: Record<string, number>; largest_files: { path: string; size_bytes: number }[]; recently_modified: { path: string; modified_at: string }[] } | null }) {
  if (!data) return <EmptyState />;

  const maxExt = Math.max(...Object.values(data.by_extension || {}), 1);
  const exts = Object.entries(data.by_extension || {}).sort(([, a], [, b]) => b - a);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Files" value={data.total_files} />
        <StatCard label="Total Dirs" value={data.total_dirs} />
        <StatCard label="Extensions" value={Object.keys(data.by_extension || {}).length} />
        <StatCard label="Total Count" value={(data.total_files || 0) + (data.total_dirs || 0)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">File Types</h3>
          <div className="space-y-1.5 max-h-72 overflow-y-auto">
            {exts.slice(0, 20).map(([ext, count]) => (
              <div key={ext} className="flex items-center gap-2">
                <span className="text-xs font-mono w-20 shrink-0 text-secondary">{ext}</span>
                <div className="flex-1 h-3 rounded bg-primary">
                  <div className="h-full rounded transition-all" style={{
                    width: `${(count / maxExt) * 100}%`,
                    backgroundColor: "var(--dt-colors-accent-default)",
                  }} />
                </div>
                <span className="text-xs shrink-0 text-tertiary">{count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Recently Modified</h3>
          {(!data.recently_modified || data.recently_modified.length === 0) ? (
            <p className="text-sm text-tertiary">No data.</p>
          ) : (
            <div className="space-y-1 max-h-72 overflow-y-auto">
              {data.recently_modified.map((f) => (
                <div key={f.path} className="flex justify-between text-xs py-0.5">
                  <span className="truncate flex-1 font-mono text-secondary">{f.path}</span>
                  <span className="ml-2 shrink-0 text-[10px] text-tertiary">
                    {f.modified_at?.slice(0, 10)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {exts.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Largest Files</h3>
          {(!data.largest_files || data.largest_files.length === 0) ? (
            <p className="text-sm text-tertiary">No data.</p>
          ) : (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {data.largest_files.map((f) => (
                <div key={f.path} className="flex justify-between text-xs py-0.5">
                  <span className="truncate flex-1 font-mono text-secondary">{f.path}</span>
                  <span className="ml-2 shrink-0 text-tertiary">{(f.size_bytes / 1024).toFixed(1)} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="stat-card">
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value">{value ?? "—"}</div>
    </div>
  );
}

function EmptyState({ message }: { message?: string }) {
  return (
    <div className="text-center py-12 text-tertiary">
      <p>{message || "No data available for this period."}</p>
    </div>
  );
}

function SkeletonCard({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="card p-4">
          <Skeleton width="40%" height={12} rounded="md" />
          <Skeleton width="60%" height={24} rounded="md" className="mt-2" />
          <Skeleton width="100%" height={80} rounded="md" className="mt-3" />
        </div>
      ))}
    </>
  );
}
