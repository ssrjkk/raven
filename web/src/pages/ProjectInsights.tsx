import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api/client";
import type { ProjectInsightsData } from "../api/types";
import { Skeleton } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

function formatMinutes(total: number): string {
  if (total < 60) return `${total} мин`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${h} ч ${m} мин`;
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl p-4 card-bordered">
      <div className="text-xs uppercase tracking-wider text-tertiary">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-tertiary mt-0.5">{sub}</div>}
    </div>
  );
}

function SkeletonCards() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="rounded-xl p-4 bg-secondary">
          <Skeleton width="50%" height={12} rounded="md" />
          <Skeleton width="70%" height={24} rounded="md" className="mt-2" />
        </div>
      ))}
    </div>
  );
}

export default function ProjectInsights() {
  const [projectId, setProjectId] = useState("default");
  const [days, setDays] = useState(30);

  const { data, isLoading } = useApiQuery<ProjectInsightsData>(
    ["projectInsights", projectId, String(days)],
    () => api.projectInsights(projectId, days),
  );

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className="text-2xl font-bold">Project Insights</h1>
        <div className="flex items-center gap-2">
          <input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="project id"
            className="px-3 py-1.5 rounded-lg text-sm bg-secondary text-primary border border-default focus:outline-none focus:border-accent"
          />
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-2 py-1.5 rounded text-sm bg-secondary text-primary border border-default"
          >
            {[7, 14, 30, 60, 90].map((d) => (
              <option key={d} value={d}>{d}д</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading || !data ? (
        <SkeletonCards />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Сэкономлено времени" value={formatMinutes(data.time_saved_minutes)} sub="за выбранный период" />
            <StatCard label="Вклад AI" value={`${data.ai_contribution_percent}%`} sub="оценка по активности" />
            <StatCard label="Успешность" value={`${data.success_rate}%`} sub="без откатов" />
            <StatCard label="Оценка стоимости токенов" value={`$${data.token_cost_estimate.toFixed(4)}`} />
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Файлов" value={String(data.files)} />
            <StatCard label="Строк кода" value={data.code_lines.toLocaleString()} />
            <StatCard label="Коммитов" value={String(data.commits)} />
            <StatCard label="Активных дней" value={String(data.active_days)} />
          </div>

          <div className="rounded-xl p-4 card-bordered">
            <h3 className="text-sm font-semibold mb-3">Коммиты по дням</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.trend} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="commitFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--dt-colors-accent-default)" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="var(--dt-colors-accent-default)" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} minTickGap={24} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "var(--dt-colors-bg-elevated)", borderColor: "var(--dt-colors-border)", color: "var(--dt-colors-text-primary)" }}
                    labelFormatter={(v) => String(v)}
                  />
                  <Area type="monotone" dataKey="commits" stroke="var(--dt-colors-accent-default)" fill="url(#commitFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <p className="text-xs text-tertiary">
            Метрики рассчитываются автоматически по активности в workspace: коммиты git, строки кода и частота откатов за выбранный период. Обновлено: {new Date(data.generated_at).toLocaleString()}
          </p>
        </div>
      )}
    </div>
  );
}
