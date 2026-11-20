import { useState } from "react";
import {
Bar, BarChart, CartesianGrid, Cell,
Line,   LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";

import { api } from "../api/client";
import { ChartCard } from "../components/ChartCard";
import { ChartTooltip } from "../components/ChartTooltip";
import PageHeader from "../components/PageHeader";
import { Skeleton } from "../components/Skeleton";
import type { AnalyticsFullData, AnalyticsMetricParts, AnalyticsMetricEntry } from "../api/types";
import { useApiQuery } from "../hooks/useApiQuery";

type Range = "1h" | "24h" | "7d";

/**
 * What a reader is told a series is, from the parts the engine resolved.
 *
 * `provider=ollama` inside `model=ollama/llama3` says the thing twice, so a label already carried by another
 * one is dropped; the rest are kept because two `tool_calls` series differ only by them.
 */
function metricLabel(metric: AnalyticsMetricParts): string {
  const values = Object.values(metric.labels).filter((value): value is string => Boolean(value));
  const identity = values.filter((value) => !values.some((other) => other !== value && other.includes(value)));
  return [metric.family, ...identity, metric.stat].filter(Boolean).join(" · ");
}

interface CostData {
  total_cost?: number;
  daily_cost?: number;
  monthly_cost?: number;
  budget_exceeded?: boolean;
  breakdown?: CostBreakdownItem[];
}

interface CostBreakdownItem {
  model?: string;
  cost: number;
}

interface ProjectMetrics {
  summary?: {
    total_files?: number;
    total_lines?: number;
    total_code?: number;
    languages?: number;
  };
  code_stats?: Record<string, { files: number; lines: number; code: number }>;
  dependencies?: {
    top_modules: { name: string; count: number }[];
    total_unique: number;
  };
  activity?: Record<string, number>;
}

// Categorical series come from the theme's chart group, so a light-theme pie is not painted in
// colours tuned for a dark one.
const COLORS = Array.from({ length: 10 }, (_, i) => `var(--dt-colors-chart-series-${i + 1})`);

export default function Analytics() {
  const [range, setRange] = useState<Range>("1h");

  const { data: full, isLoading: loading } = useApiQuery<AnalyticsFullData | null>(["analyticsFull"], () => api.analyticsFull().catch((e) => { console.error("analytics load failed:", e); return null; }));
  const { data: costData } = useApiQuery<CostData | null>(["costSummary"], () => api.costSummary(24).catch(() => null));
  const { data: projectMetrics } = useApiQuery<ProjectMetrics | null>(["projectMetrics"], () => api.projectMetrics().catch(() => null));

  const data = range === "1h" ? full?.last_hour : full?.last_24h;
  const summaryData = full?.summary;
  const metricMap: Record<string, AnalyticsMetricEntry> = {};
  if (summaryData?.metrics) {
    for (const m of summaryData.metrics) {
      metricMap[m.name] = m;
    }
  }

  const messageSeries = data?.message_series;
  const errorSeries = data?.error_series;
  const errorRate = data?.error_rate ?? 0;
  const toolBd = full?.tool_breakdown ?? { total: 0, success: 0, errors: 0, success_series: [], error_series: [] };
  const toolUsage = range === "1h" ? full?.tool_usage_1h : full?.tool_usage;
  const summaryMetrics = summaryData?.metrics?.slice(0, 30) ?? [];

  const deps = projectMetrics?.dependencies;
  const depsModules = deps?.top_modules;
  const costBreakdown = costData?.breakdown;

  const rangeOpts: { key: Range; label: string }[] = [
    { key: "1h", label: "Last Hour" },
    { key: "24h", label: "Last 24h" },
    { key: "7d", label: "Last 7 Days (summary)" },
  ];

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton width={220} height={28} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card-bordered p-4">
              <Skeleton width={64} height={12} rounded="md" />
              <Skeleton width={48} height={32} rounded="md" className="mt-2" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2].map((i) => (
            <div key={i} className="card-bordered p-4">
              <Skeleton height={220} rounded="lg" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const latencyMetrics = summaryMetrics.filter((m) =>
    m.name.includes("latency") || m.name.includes("p99") || m.name.includes("duration")
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Advanced Analytics"
        subtitle="Usage, performance, and cost insights"
        actions={
          <div className="flex gap-1 bg-tertiary rounded-lg p-1">
            {rangeOpts.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${range === r.key ? "bg-accent on-accent" : "text-secondary"}`}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />

      {/* Project Metrics */}
      {projectMetrics?.summary && (
        <>
          <div>
            <h2 className="text-lg font-semibold mb-3">Project Metrics</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <MetricCard label="Total Files" value={projectMetrics.summary.total_files?.toLocaleString() ?? "—"} />
              <MetricCard label="Total Lines" value={projectMetrics.summary.total_lines?.toLocaleString() ?? "—"} />
              <MetricCard label="Code Lines" value={projectMetrics.summary.total_code?.toLocaleString() ?? "—"} />
              <MetricCard label="Languages" value={String(projectMetrics.summary.languages ?? "—")} />
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Language Breakdown */}
            {projectMetrics.code_stats && Object.keys(projectMetrics.code_stats).length > 0 && (
              <ChartCard title="Language Breakdown">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={Object.entries(projectMetrics.code_stats)
                      .sort(([, a], [, b]) => b.code - a.code)
                      .slice(0, 12)
                      .map(([lang, stats]) => ({
                        name: lang,
                        files: stats.files,
                        lines: stats.lines,
                        code: stats.code,
                      }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                    <XAxis dataKey="name" stroke="var(--dt-colors-text-secondary)" fontSize={10} />
                    <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                    <Tooltip
                      content={<ChartTooltip />}
                    />
                    <Bar dataKey="code" fill="var(--dt-colors-chart-series-1)" radius={[4, 4, 0, 0]} name="Code Lines" />
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>
            )}

            {/* Top Dependencies */}
            {depsModules && depsModules.length > 0 && (
              <ChartCard title={`Top Dependencies (${deps.total_unique} unique)`}>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={depsModules.slice(0, 15)}
                    layout="vertical"
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                    <XAxis type="number" stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                    <YAxis type="category" dataKey="name" stroke="var(--dt-colors-text-secondary)" fontSize={10} width={100} />
                    <Tooltip
                      content={<ChartTooltip />}
                    />
                    <Bar dataKey="count" fill="var(--dt-colors-chart-series-4)" radius={[0, 4, 4, 0]} name="References" />
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>
            )}
          </div>

          {/* Activity */}
          {projectMetrics.activity && Object.keys(projectMetrics.activity).length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
              {Object.entries(projectMetrics.activity).map(([period, count]) => (
                <MetricCard key={period} label={`Files changed ${period}`} value={String(count)} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Summary Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Messages Received" value={data?.received?.toLocaleString() ?? "—"} />
        <MetricCard
          label="Errors"
          value={data?.errors?.toLocaleString() ?? "—"}
          danger={errorRate > 5}
        />
        <MetricCard
          label="Error Rate"
          value={errorRate != null ? `${errorRate.toFixed(1)}%` : "—"}
          danger={errorRate > 5}
        />
        <MetricCard label="Tool Calls" value={toolBd?.total?.toLocaleString() ?? "—"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Messages Over Time */}
        {messageSeries && messageSeries.length > 0 && (
          <ChartCard title="Messages Received Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={messageSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <Tooltip
                  content={<ChartTooltip formatLabel={(v) => new Date(Number(v) * 1000).toLocaleString()} />}
                />
                <Line type="monotone" dataKey="avg" stroke="var(--dt-colors-chart-series-1)" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="var(--dt-colors-chart-series-5)" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Errors Over Time */}
        {errorSeries && errorSeries.length > 0 && (
          <ChartCard title="Errors Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={errorSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <Tooltip
                  content={<ChartTooltip formatLabel={(v) => new Date(Number(v) * 1000).toLocaleString()} />}
                />
                <Line type="monotone" dataKey="avg" stroke="var(--dt-colors-status-error)" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="var(--dt-colors-chart-series-5)" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Tool Calls Success/Error */}
        {toolBd.success_series && toolBd.success_series.length > 0 && (
          <ChartCard title="Tool Calls Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={toolBd.success_series.map((s, i: number) => ({
                ts: s.ts,
                success: s.avg,
                error: toolBd.error_series?.[i]?.avg ?? 0,
              }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <Tooltip
                  content={<ChartTooltip formatLabel={(v) => new Date(Number(v) * 1000).toLocaleString()} />}
                />
                <Line type="monotone" dataKey="success" stroke="var(--dt-colors-status-success)" strokeWidth={2} dot={false} name="Success" />
                <Line type="monotone" dataKey="error" stroke="var(--dt-colors-status-error)" strokeWidth={2} dot={false} name="Error" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Tool Usage Breakdown */}
        {toolUsage && toolUsage.length > 0 && (
          <ChartCard title="Tool Usage Distribution">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={toolUsage.slice(0, 10).map((t, i: number) => ({
                    name: t.name.length > 25 ? t.name.slice(0, 22) + "..." : t.name,
                    value: t.total,
                    fill: COLORS[i % COLORS.length],
                  }))}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`}
                >
                  {toolUsage.slice(0, 10).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  content={<ChartTooltip />}
                />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Top Tools Bar Chart */}
        {toolUsage && toolUsage.length > 0 && (
          <ChartCard title="Top Tools by Call Count">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={toolUsage.slice(0, 15).map((t) => ({
                  name: t.name.length > 20 ? t.name.slice(0, 17) + "..." : t.name,
                  calls: t.total,
                }))}
                layout="vertical"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis type="number" stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <YAxis type="category" dataKey="name" stroke="var(--dt-colors-text-secondary)" fontSize={10} width={150} />
                <Tooltip
                  content={<ChartTooltip />}
                />
                <Bar dataKey="calls" fill="var(--dt-colors-chart-series-1)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Latency Metrics */}
        {latencyMetrics.length > 0 && (
          <ChartCard title="Latency / Response Time (avg)">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart
                data={latencyMetrics.slice(0, 15).map((m) => {
                  const label = metricLabel(m);
                  return { name: label.length > 25 ? `${label.slice(0, 22)}...` : label, fullName: m.name, value: m.avg };
                })}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="name" stroke="var(--dt-colors-text-secondary)" fontSize={10} angle={-30} textAnchor="end" height={60} />
                <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={11} />
                <Tooltip
                  content={<ChartTooltip formatLabel={(v, items) => String(items[0]?.payload?.fullName ?? v ?? "")} />}
                />
                <Bar dataKey="value" fill="var(--dt-colors-chart-series-3)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Cost by Model */}
        {costBreakdown && costBreakdown.length > 0 && (
          <ChartCard title="Cost by Model">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={costBreakdown.slice(0, 8).map((b, i: number) => ({
                    name: (b.model?.length ?? 0) > 20 ? b.model!.slice(0, 17) + "..." : b.model || "unknown",
                    value: b.cost,
                    fill: COLORS[i % COLORS.length],
                  }))}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`}
                >
                  {costBreakdown.slice(0, 8).map((_, i: number) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  content={<ChartTooltip />}
                />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>
        )}
      </div>

      {/* Cost Summary Cards */}
      {costData && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Cost Summary (24h)</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard label="Total Cost" value={costData.total_cost != null ? `$${costData.total_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Daily Cost" value={costData.daily_cost != null ? `$${costData.daily_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Monthly Cost" value={costData.monthly_cost != null ? `$${costData.monthly_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Budget Exceeded" value={costData.budget_exceeded ? "Yes" : "No"} danger={costData.budget_exceeded} />
          </div>
        </div>
      )}

      {/* Detailed Metrics Table */}
      {summaryMetrics.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-3">All Metrics ({summaryMetrics.length})</h2>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-tertiary">
                  <th className="text-left pb-2 font-medium sticky top-0 bg-card">Metric Name</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-card">Avg</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-card">Max</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-card">Samples</th>
                </tr>
              </thead>
              <tbody>
                {summaryMetrics.map((m) => (
                  <tr key={m.name} className="border-t border-default">
                    <td className="py-1.5 font-mono text-xs text-primary">{m.name}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-secondary">{m.avg}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-secondary">{m.max}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-secondary">{m.samples}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Latency Series Detail */}
      {data?.latency_series && data.latency_series.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-3">Latency Detail Series</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {data.latency_series.slice(0, 4).map((entry) =>
              entry.series.length > 0 ? (
                <ChartCard key={entry.metric} title={metricLabel(entry)} className="">
                  <ResponsiveContainer width="100%" height={150}>
                    <LineChart data={entry.series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                      <XAxis dataKey="ts" tickFormatter={(v: number) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-secondary)" fontSize={10} />
                      <YAxis stroke="var(--dt-colors-text-secondary)" fontSize={10} />
                      <Tooltip
                        content={<ChartTooltip />}
                      />
                      <Line type="monotone" dataKey="avg" stroke="var(--dt-colors-chart-series-2)" strokeWidth={1.5} dot={false} name="Avg" />
                      <Line type="monotone" dataKey="max" stroke="var(--dt-colors-chart-series-6)" strokeWidth={1} dot={false} name="Max" strokeDasharray="3 1" />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartCard>
              ) : null
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className={`stat-card ${danger ? "stat-card-danger" : ""}`}>
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value">{value}</div>
    </div>
  );
}

