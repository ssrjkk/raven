import { useState, useEffect } from "react";
import { api } from "../api/client";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";

type Range = "1h" | "24h" | "7d";

const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#14b8a6", "#84cc16", "#f97316"];

export default function Analytics() {
  const [range, setRange] = useState<Range>("1h");
  const [loading, setLoading] = useState(true);
  const [full, setFull] = useState<any>(null);
  const [costData, setCostData] = useState<any>(null);

  useEffect(() => {
    loadData();
  }, [range]);

  async function loadData() {
    setLoading(true);
    try {
      const [f, c] = await Promise.all([
        api.analyticsFull(),
        api.costSummary(24).catch(() => null),
      ]);
      setFull(f);
      setCostData(c);
    } catch (e) {
      console.error("analytics load failed:", e);
    } finally {
      setLoading(false);
    }
  }

  const data = range === "1h" ? full?.last_hour : full?.last_24h;
  const summaryData = full?.summary;
  const metricMap: Record<string, any> = {};
  if (summaryData?.metrics) {
    for (const m of summaryData.metrics) {
      metricMap[m.name] = m;
    }
  }

  const errorRate = data?.error_rate ?? 0;
  const toolBd = full?.tool_breakdown ?? {};
  const toolUsage = range === "1h" ? full?.tool_usage_1h : full?.tool_usage;
  const summaryMetrics = summaryData?.metrics?.slice(0, 30) ?? [];

  const rangeOpts: { key: Range; label: string }[] = [
    { key: "1h", label: "Last Hour" },
    { key: "24h", label: "Last 24h" },
    { key: "7d", label: "Last 7 Days (summary)" },
  ];

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Advanced Analytics</h1>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4 animate-pulse">
              <div className="h-3 bg-gray-800 rounded w-16 mb-3" />
              <div className="h-8 bg-gray-800 rounded w-12" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2].map((i) => (
            <div key={i} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4 animate-pulse h-64" />
          ))}
        </div>
      </div>
    );
  }

  const latencyMetrics = summaryMetrics.filter((m: any) =>
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
        {data?.message_series?.length > 0 && (
          <ChartCard title="Messages Received Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={data.message_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="avg" stroke="#6366f1" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="#f59e0b" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Errors Over Time */}
        {data?.error_series?.length > 0 && (
          <ChartCard title="Errors Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={data.error_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="avg" stroke="#ef4444" strokeWidth={2} dot={false} name="Avg" activeDot={{ r: 4 }} />
                <Line type="monotone" dataKey="max" stroke="#f59e0b" strokeWidth={1} dot={false} name="Max" strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Tool Calls Success/Error */}
        {toolBd?.success_series?.length > 0 && (
          <ChartCard title="Tool Calls Over Time">
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={toolBd.success_series.map((s: any, i: number) => ({
                ts: s.ts,
                success: s.avg,
                error: toolBd.error_series?.[i]?.avg ?? 0,
              }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                <XAxis dataKey="ts" tickFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <YAxis stroke="var(--dt-colors-text-tertiary)" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)", border: "1px solid var(--dt-colors-border-default)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleString()}
                />
                <Line type="monotone" dataKey="success" stroke="#22c55e" strokeWidth={2} dot={false} name="Success" />
                <Line type="monotone" dataKey="error" stroke="#ef4444" strokeWidth={2} dot={false} name="Error" />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Tool Usage Breakdown */}
        {toolUsage?.length > 0 && (
          <ChartCard title="Tool Usage Distribution">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={toolUsage.slice(0, 10).map((t: any, i: number) => {
                    const short = t.name.replace("raven_tool_calls_total{tool=", "").replace(/}$/, "").replace(/,category=.*/, "");
                    return { name: short.length > 25 ? short.slice(0, 22) + "..." : short, value: t.total, fill: COLORS[i % COLORS.length] };
                  })}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}
                >
                  {toolUsage.slice(0, 10).map((_: any, i: number) => (
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
        {toolUsage?.length > 0 && (
          <ChartCard title="Top Tools by Call Count">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={toolUsage.slice(0, 15).map((t: any) => {
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
                data={latencyMetrics.slice(0, 15).map((m: any) => ({
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
                  labelFormatter={(v: any, payload: any) => (payload?.[0] as any)?.payload?.fullName || v}
                />
                <Bar dataKey="value" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        )}

        {/* Cost by Model */}
        {costData?.breakdown?.length > 0 && (
          <ChartCard title="Cost by Model">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={costData.breakdown.slice(0, 8).map((b: any, i: number) => ({
                    name: b.model?.length > 20 ? b.model.slice(0, 17) + "..." : b.model || "unknown",
                    value: b.cost,
                    fill: COLORS[i % COLORS.length],
                  }))}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}
                >
                  {costData.breakdown.slice(0, 8).map((_: any, i: number) => (
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
            <MetricCard label="Total Cost" value={costData.total_cost != null ? `$${costData.total_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Daily Cost" value={costData.daily_cost != null ? `$${costData.daily_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Monthly Cost" value={costData.monthly_cost != null ? `$${costData.monthly_cost.toFixed(4)}` : "—"} />
            <MetricCard label="Budget Exceeded" value={costData.budget_exceeded ? "⚠ Yes" : "No"} danger={costData.budget_exceeded} />
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
                <tr style={{ color: "var(--dt-colors-text-tertiary)" }}>
                  <th className="text-left pb-2 font-medium sticky top-0 bg-gray-900">Metric Name</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Avg</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Max</th>
                  <th className="text-right pb-2 font-medium sticky top-0 bg-gray-900">Samples</th>
                </tr>
              </thead>
              <tbody>
                {summaryMetrics.map((m: any) => (
                  <tr key={m.name} className="border-t" style={{ borderColor: "var(--dt-colors-border-default)" }}>
                    <td className="py-1.5 font-mono text-xs" style={{ color: "var(--dt-colors-text-primary)" }}>{m.name}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{ color: "var(--dt-colors-text-secondary)" }}>{m.avg}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{ color: "var(--dt-colors-text-secondary)" }}>{m.max}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{ color: "var(--dt-colors-text-secondary)" }}>{m.samples}</td>
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
            {Object.entries(data.latency_series).slice(0, 4).map(([name, series]: [string, any]) =>
              series?.length > 0 ? (
                <div key={name}>
                  <div className="text-xs font-mono mb-1" style={{ color: "var(--dt-colors-text-secondary)" }}>{name}</div>
                  <ResponsiveContainer width="100%" height={150}>
                    <LineChart data={series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--dt-colors-border-default)" />
                      <XAxis dataKey="ts" tickFormatter={(v: any) => new Date(Number(v) * 1000).toLocaleTimeString()} stroke="var(--dt-colors-text-tertiary)" fontSize={9} />
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
      <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--dt-colors-text-secondary)" }}>{title}</h2>
      {children}
    </div>
  );
}
