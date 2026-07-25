import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type BudgetInfo, type CostSummary, type CostUsageRecord, type PricingInfo } from "../api/client";
import { Skeleton } from "../components/Skeleton";
import TokenUsageBar from "../components/TokenUsageBar";
import { useApiQuery } from "../hooks/useApiQuery";

export default function CostManagement() {
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [budgetName, setBudgetName] = useState("");
  const [dailyLimit, setDailyLimit] = useState(10);
  const [monthlyLimit, setMonthlyLimit] = useState(300);

  const { data: summary, isLoading } = useApiQuery<CostSummary | null>(["costSummary"], () => api.costSummary(24));
  const { data: pricingData } = useApiQuery<{ pricing: Record<string, PricingInfo> }>(["costPricing"], () => api.costPricing());
  const { data: budgetsData } = useApiQuery<{ budgets: BudgetInfo[] }>(["costBudgets"], () => api.costBudgets());
  const { data: recentUsageData } = useApiQuery<{ usage: CostUsageRecord[] }>(["costRecentUsage"], () => api.costRecentUsage(50));

  const pricing = pricingData?.pricing ?? {};
  const budgets = budgetsData?.budgets ?? [];
  const recentUsage = recentUsageData?.usage ?? [];

  const createBudget = useMutation({
    mutationFn: () => api.costCreateBudget(budgetName, dailyLimit, monthlyLimit),
    onSuccess: (r) => {
      setMsg(`Budget created: ${r.name}`);
      setBudgetName(""); setDailyLimit(10); setMonthlyLimit(300);
      qc.invalidateQueries({ queryKey: ["costBudgets"] });
      qc.invalidateQueries({ queryKey: ["costSummary"] });
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : "Failed to create budget");
    },
  });

  const deleteBudget = useMutation({
    mutationFn: (id: string) => api.costDeleteBudget(id),
    onSuccess: () => {
      setMsg("Budget deleted");
      qc.invalidateQueries({ queryKey: ["costBudgets"] });
      qc.invalidateQueries({ queryKey: ["costSummary"] });
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : "Failed to delete budget");
    },
  });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Cost Management</h1>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {isLoading && !summary ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))", border: "1px solid var(--dt-colors-border-default)" }}>
              <Skeleton width={64} height={12} rounded="md" />
              <Skeleton width={48} height={32} rounded="md" className="mt-2" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-6">
          {summary && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: "Total Cost", value: `$${summary.total_cost?.toFixed(4)}`, danger: summary.total_cost > 1 },
                  { label: "Daily Cost", value: `$${summary.daily_cost?.toFixed(4)}`, danger: summary.daily_cost > 0.5 },
                  { label: "Monthly Cost", value: `$${summary.monthly_cost?.toFixed(4)}`, danger: summary.monthly_cost > 10 },
                  { label: "LLM Calls", value: summary.total_calls },
                ].map((c) => (
                  <div key={c.label} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
                    <div className="text-xs text-gray-500 uppercase tracking-wider">{c.label}</div>
                    <div className="text-2xl font-bold mt-1" style={{ color: c.danger ? "var(--dt-colors-danger-default)" : "inherit" }}>
                      {String(c.value)}
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="p-4 rounded-lg bg-secondary">
                  <h2 className="text-lg font-semibold mb-3">Cost by Model ({Object.keys(summary.by_model || {}).length})</h2>
                  {!summary.by_model || Object.keys(summary.by_model).length === 0 ? (
                    <p className="text-sm text-tertiary">No usage recorded yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {Object.entries(summary.by_model).map(([model, data]) => (
                        <div key={model} className="p-2 rounded-lg bg-tertiary">
                          <div className="flex justify-between text-sm">
                            <span className="font-medium">{model}</span>
                            <span>${data.cost?.toFixed(4)}</span>
                          </div>
                          <div className="text-xs text-tertiary">
                            {data.calls} calls | {data.input_tokens} in / {data.output_tokens} out
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="p-4 rounded-lg bg-secondary">
                  <h2 className="text-lg font-semibold mb-3">Budgets</h2>
                  <div className="space-y-2 mb-3">
                    <input placeholder="Budget name" value={budgetName} onChange={e => setBudgetName(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
                    <div className="grid grid-cols-2 gap-2">
                      <input type="number" placeholder="Daily limit ($)" value={dailyLimit} onChange={e => setDailyLimit(parseFloat(e.target.value) || 0)}
                        className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
                      <input type="number" placeholder="Monthly limit ($)" value={monthlyLimit} onChange={e => setMonthlyLimit(parseFloat(e.target.value) || 0)}
                        className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
                    </div>
                    <button onClick={() => createBudget.mutate()} disabled={createBudget.isPending || !budgetName}
                      className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
                      Add Budget
                    </button>
                  </div>
                  {budgets.length === 0 ? (
                    <p className="text-sm text-tertiary">No budgets configured.</p>
                  ) : (
                    <div className="space-y-2">
                      {budgets.map((b) => {
                        const dailyPct = b.daily_limit > 0 ? ((b.current_daily || 0) / b.daily_limit * 100) : 0;
                        return (
                          <div key={b.id} className="p-2 rounded-lg text-sm bg-tertiary">
                            <div className="flex justify-between items-center">
                              <span className="font-medium">{b.name}</span>
                              <button onClick={() => deleteBudget.mutate(b.id)} className="text-xs text-danger">Delete</button>
                            </div>
                            <div className="flex gap-4 mt-1 text-xs text-tertiary">
                              <span>Daily: ${(b.current_daily || 0).toFixed(2)} / ${b.daily_limit?.toFixed(2)}</span>
                              <span>Monthly: ${(b.current_monthly || 0).toFixed(2)} / ${b.monthly_limit?.toFixed(2)}</span>
                            </div>
                            <div className="w-full h-1.5 rounded-full mt-1 bg-primary">
                              <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(dailyPct, 100)}%`, backgroundColor: dailyPct > 80 ? "var(--dt-colors-danger-default)" : dailyPct > 50 ? "var(--dt-colors-warning-default)" : "var(--dt-colors-success-default)" }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Model Pricing</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-tertiary">
                    <th className="text-left pb-2 font-medium">Model</th>
                    <th className="text-right pb-2 font-medium">Input ($/1K)</th>
                    <th className="text-right pb-2 font-medium">Output ($/1K)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(pricing).map(([model, rates]) => (
                    <tr key={model} className="border-t border-default">
                      <td className="py-1.5">{model}</td>
                      <td className="py-1.5 text-right font-mono">${rates.input_per_1k?.toFixed(5)}</td>
                      <td className="py-1.5 text-right font-mono">${rates.output_per_1k?.toFixed(5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">
              Recent Usage
              {recentUsage.length > 0 && (
                <span className="ml-2 text-sm font-normal text-tertiary">
                  ({recentUsage.length} requests)
                </span>
              )}
            </h2>
            {recentUsage.length === 0 ? (
              <p className="text-sm text-tertiary">No usage recorded yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-tertiary">
                      <th className="text-left pb-2 font-medium">Model</th>
                      <th className="text-right pb-2 font-medium">Tokens</th>
                      <th className="text-right pb-2 font-medium">Cost</th>
                      <th className="text-right pb-2 font-medium">Duration</th>
                      <th className="text-right pb-2 font-medium">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentUsage.map((r) => (
                      <tr key={r.id} className="border-t border-default">
                        <td className="py-1.5 pr-3">
                          <span className="text-[11px] px-1.5 py-0.5 rounded btn-secondary-text">
                            {r.model}
                          </span>
                        </td>
                        <td className="py-1.5 text-right font-mono text-xs">
                          <TokenUsageBar inputTokens={r.input_tokens} outputTokens={r.output_tokens} compact />
                        </td>
                        <td className="py-1.5 text-right font-mono text-xs">
                          ${r.cost?.toFixed(6)}
                        </td>
                        <td className="py-1.5 text-right font-mono text-xs text-tertiary">
                          {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "РІР‚вЂќ"}
                        </td>
                        <td className="py-1.5 text-right text-xs text-tertiary">
                          {formatTime(r.timestamp)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatTime(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
