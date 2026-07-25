import { useState } from "react";
import {
Bar, BarChart, CartesianGrid, Cell,
Line,   LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";

import { api } from "../api/client";
import { Skeleton } from "../components/Skeleton";
import { useApiQuery } from "../hooks/useApiQuery";

type Range = "1h" | "24h" | "7d";

interface MetricEntry {
  name: string;
  avg: number;
  max: number;
  samples: number;
}

interface AnalyticsData {
  last_hour?: AnalyticsRangeData;
  last_24h?: AnalyticsRangeData;
  summary?: { metrics: MetricEntry[] };
  tool_breakdown?: { total: number; success_series?: TimeSeriesPoint[]; error_series?: TimeSeriesPoint[] };
  tool_usage_1h?: ToolUsageItem[];
  tool_usage?: ToolUsageItem[];
}

interface AnalyticsRangeData {
  received?: number;
  errors?: number;
  error_rate?: number;
  message_series?: TimeSeriesPoint[];
  error_series?: TimeSeriesPoint[];
  latency_series?: Record<string, TimeSeriesPoint[]>;
}

interface TimeSeriesPoint {
  ts: number;
  avg: number;
  max: number;
}

interface ToolUsageItem {
  name: string;
  total: number;
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

const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#14b8a6", "#84cc16", "#f97316"];

export default function Analytics() {
  const [range, setRange] = useState<Range>("1h");

  const { data: full, isLoading: loading } = useApiQuery<AnalyticsData | null>(["analyticsFull"], () => api.analyticsFull().catch((e) => { console.error("analytics load failed:", e); return null; }));
  const { data: costData } = useApiQuery<CostData | null>(["costSummary"], () => api.costSummary(24).catch(() => null));
  const { data: projectMetrics } = useApiQuery<ProjectMetrics | null>(["projectMetrics"], () => api.projectMetrics().catch(() => null));

  const data = range === "1h" ? full?.last_hour : full?.last_24h;
  const summaryData = full?.summary;
  const metricMap: Record<string, MetricEntry> = {};
  if (summaryData?.metrics) {
    for (const m of summaryData.metrics) {
      metricMap[m.name] = m;
    }
  }

  const messageSeries = data?.message_series;
  const errorSeries = data?.error_series;
  const errorRate = data?.error_rate ?? 0;
  const toolBd = full?.tool_breakdown ?? { total: 0, success_series: [], error_series: [] };
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
            <div key={i} className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))", border: "1px solid var(--dt-colors-border-default)" }}>
              <Skeleton width={64} height={12} rounded="md" />
              <Skeleton width={48} height={32} rounded="md" className="mt-2" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2].map((i) => (
            <div key={i} className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))", border: "1px solid var(--dt-colors-border-default)" }}>
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Advanced Analytics</h1>
        <div className="flex gap-1 bg-gray-800/60 rounded-lg p-1">
          {rangeOpts.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className="px-3 py-1.5 rounded-md text-sm font-medium transition"
              style={{
                backgroundColor: range === r.key ? "var(--dt-colors-accent-default)" : "transparent",
                color: range === r.key ? "#fff" : "var(--dt-colors-text-secondary)",
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Project Metrics */}
      {projectMetrics?.summary && (
        <>
          <div>
            <h2 className="text-lg font-semibold mb-3">Project Metrics</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <MetricCard label="Total Files" value={projectMetrics.summary.total_files?.toLocaleString() ?? "РІР‚вЂќ"} />
              <MetricCard label="Total Lines" value={projectMetrics.summary.total_lines?.toLocaleString() ?? "РІР‚вЂќ"} />
              <MetricCard label="Code Lines" value={projectMetrics.summary.total_code?.toLocaleString() ?? "РІР‚вЂќ"} />
              <MetricCard label="Languages" value={String(projectMetrics.summary.languages ?? "РІР‚вЂќ")} />
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
                    <XAxis dataKey="name" stroke="var(--dt-colors-text-tertiary)" fontSize={10} />
                    <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                    />
                    <Bar dataKey="code" fill="#6366f1" radius={[4, 4, 0, 0]} name="Code Lines" />
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
                    <XAxis type="number" stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                    <YAxis type="category" dataKey="name" stroke="var(--dt-colors-text-tertiary)" fontSize={9} width={100} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                    />
                    <Bar dataKey="count" fill="#22c55e" radius={[0, 4, 4, 0]} name="References" />
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
        <MetricCard label="Messages Received" value={data?.received?.toLocaleString() ?? "РІР‚вЂќ"} />
        <MetricCard
          label="Errors"
          value={data?.errors?.toLocaleString() ?? "РІР‚вЂќ"}
          danger={errorRate > 5}
        />
        <MetricCard
          label="Error Rate"
          value={errorRate != null ? `${errorRate.toFixed(1)}%` : "РІР‚вЂќ"}
          danger={errorRate > 5}
        />
        <MetricCard label="Tool Calls" value={toolBd?.total?.toLocaleString() ?? "РІР‚вЂќ"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Messages Over Time */}
        {messageSeries && messageSeries.length > 0 && (
          <ChartCard title="Messages Received Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={messageSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="avg" stroke="#6366f1" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="#f59e0b" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
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
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="avg" stroke="#ef4444" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="#f59e0b" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
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
                <XAxis dataKey="ts" tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="success" stroke="#22c55e" strokeWidth={2} dot={false} name="Success" />
                <Line type="monotone" dataKey="error" stroke="#ef4444" strokeWidth={2} dot={false} name="Error" />
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
                  data={toolUsage.slice(0, 10).map((t, i: number) => {
                    const short = t.name.replace("raven_tool_calls_total{tool=", "").replace(/}$/, "").replace(/,category=.*/, "");
                    return { name: short.length > 25 ? short.slice(0, 22) + "..." : short, value: t.total, fill: COLORS[i % COLORS.length] };
                  })}
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
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
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
                data={toolUsage.slice(0, 15).map((t) => {
                  const short = t.name.replace("raven_tool_calls_total{tool=", "").replace(/}$/, "").replace(/,category=.*/, "");
                  return { name: short.length > 20 ? short.slice(0, 17) + "..." : short, calls: t.total };
                })}
                layout="vertical"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis type="number" stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis type="category" dataKey="name" stroke="var(--dt-colors-text-tertiary)" fontSize={10} width={150} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="calls" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Latency Metrics */}
        {latencyMetrics.length > 0 && (
          <ChartCard title="Latency / Response Time (avg)">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart
                data={latencyMetrics.slice(0, 15).map((m) => ({
                  name: m.name.replace("raven_", "").length > 25
                    ? m.name.replace("raven_", "").slice(0, 22) + "..."
                    : m.name.replace("raven_", ""),
                  fullName: m.name,
                  value: m.avg,
                }))}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="name" stroke="var(--dt-colors-text-tertiary)" fontSize={9} angle={-30} textAnchor="end" height={60} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v, payload: readonly { payload?: { fullName?: string } }[]) => payload?.[0]?.payload?.fullName || v}
                />
                <Bar dataKey="value" fill="#06b6d4" radius={[4, 4, 0, 0]} />
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
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
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
            <MetricCard label="Total Cost" value={costData.total_cost != null ? `$${costData.total_cost.toFixed(4)}` : "РІР‚вЂќ"} />
            <MetricCard label="Daily Cost" value={costData.daily_cost != null ? `$${costData.daily_cost.toFixed(4)}` : "РІР‚вЂќ"} />
            <MetricCard label="Monthly Cost" value={costData.monthly_cost != null ? `$${costData.monthly_cost.toFixed(4)}` : "РІР‚вЂќ"} />
            <MetricCard label="Budget Exceeded" value={costData.budget_exceeded ? "РІС™В  Yes" : "No"} danger={costData.budget_exceeded} />
          </div>
        </div>
      )}

      {/* Detailed Metrics Table */}
      {summaryMetrics.length > 0 && (
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-lg font-semibold mb-3">All Metrics ({summaryMetrics.length})</h2>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-tertiary">
                  <th className="text-left pb-2 font-medium sticky top-0 bg-gray-900">Metric Name</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Avg</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Max</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Samples</th>
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
      {data?.latency_series && Object.keys(data.latency_series).length > 0 && (
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-lg font-semibold mb-3">Latency Detail Series</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {Object.entries(data.latency_series).slice(0, 4).map(([name, series]) =>
              series?.length > 0 ? (
                <div key={name}>
                  <div className="text-xs font-mono mb-1 text-secondary">{name}</div>
                  <ResponsiveContainer width="100%" height={150}>
                    <LineChart data={series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                      <XAxis dataKey="ts" tickFormatter={(v: number) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={9} />
                      <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={9} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 11 }}
                      />
                      <Line type="monotone" dataKey="avg" stroke="#8b5cf6" strokeWidth={1.5} dot={false} name="Avg" />
                      <Line type="monotone" dataKey="max" stroke="#f97316" strokeWidth={1} dot={false} name="Max" strokeDasharray="3 1" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
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
    <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider">{label}</div>
      <div
        className="text-2xl font-bold mt-1"
        style={{ color: danger ? "var(--dt-colors-danger-default)" : "inherit" }}
      >
        {value}
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <h2 className="text-sm font-semibold mb-3 text-secondary">{title}</h2>
      {children}
    </div>
  );
}
