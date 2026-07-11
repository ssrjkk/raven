import { useState, useEffect } from "react";
import { api } from "../api/client";

export default function CostManagement() {
  const [summary, setSummary] = useState<any>(null);
  const [pricing, setPricing] = useState<Record<string, any>>({});
  const [budgets, setBudgets] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [budgetName, setBudgetName] = useState("");
  const [dailyLimit, setDailyLimit] = useState(10);
  const [monthlyLimit, setMonthlyLimit] = useState(300);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    setLoading(true); setError("");
    try {
      const [s, p, b] = await Promise.all([
        api.costSummary(24),
        api.costPricing(),
        api.costBudgets(),
      ]);
      setSummary(s);
      setPricing(p.pricing);
      setBudgets(b.budgets);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleCreateBudget() {
    setMsg(""); setError(""); setLoading(true);
    try {
      const r: any = await api.costCreateBudget(budgetName, dailyLimit, monthlyLimit);
      setMsg(`Budget created: ${r.name}`);
      setBudgetName(""); setDailyLimit(10); setMonthlyLimit(300);
      loadAll();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleDeleteBudget(id: string) {
    setError(""); setMsg("");
    try {
      await api.costDeleteBudget(id);
      setMsg("Budget deleted");
      loadAll();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Cost Management</h1>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {loading && !summary ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4 animate-pulse">
              <div className="h-3 bg-gray-800 rounded w-16 mb-3" />
              <div className="h-8 bg-gray-800 rounded w-12" />
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
                <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
                  <h2 className="text-lg font-semibold mb-3">Cost by Model ({Object.keys(summary.by_model || {}).length})</h2>
                  {!summary.by_model || Object.keys(summary.by_model).length === 0 ? (
                    <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No usage recorded yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {Object.entries(summary.by_model).map(([model, data]: [string, any]) => (
                        <div key={model} className="p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                          <div className="flex justify-between text-sm">
                            <span className="font-medium">{model}</span>
                            <span>${data.cost?.toFixed(4)}</span>
                          </div>
                          <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                            {data.calls} calls | {data.input_tokens} in / {data.output_tokens} out
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
                  <h2 className="text-lg font-semibold mb-3">Budgets</h2>
                  <div className="space-y-2 mb-3">
                    <input placeholder="Budget name" value={budgetName} onChange={e => setBudgetName(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                    <div className="grid grid-cols-2 gap-2">
                      <input type="number" placeholder="Daily limit ($)" value={dailyLimit} onChange={e => setDailyLimit(parseFloat(e.target.value) || 0)}
                        className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                      <input type="number" placeholder="Monthly limit ($)" value={monthlyLimit} onChange={e => setMonthlyLimit(parseFloat(e.target.value) || 0)}
                        className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                    </div>
                    <button onClick={handleCreateBudget} disabled={loading || !budgetName}
                      className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                      Add Budget
                    </button>
                  </div>
                  {budgets.length === 0 ? (
                    <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No budgets configured.</p>
                  ) : (
                    <div className="space-y-2">
                      {budgets.map((b: any) => {
                        const dailyPct = b.daily_limit > 0 ? ((b.current_daily || 0) / b.daily_limit * 100) : 0;
                        return (
                          <div key={b.id} className="p-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                            <div className="flex justify-between items-center">
                              <span className="font-medium">{b.name}</span>
                              <button onClick={() => handleDeleteBudget(b.id)} className="text-xs" style={{ color: "var(--dt-colors-danger-default)" }}>Delete</button>
                            </div>
                            <div className="flex gap-4 mt-1 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                              <span>Daily: ${(b.current_daily || 0).toFixed(2)} / ${b.daily_limit?.toFixed(2)}</span>
                              <span>Monthly: ${(b.current_monthly || 0).toFixed(2)} / ${b.monthly_limit?.toFixed(2)}</span>
                            </div>
                            <div className="w-full h-1.5 rounded-full mt-1" style={{ backgroundColor: "var(--dt-colors-bg-primary)" }}>
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

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Model Pricing</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ color: "var(--dt-colors-text-tertiary)" }}>
                    <th className="text-left pb-2 font-medium">Model</th>
                    <th className="text-right pb-2 font-medium">Input ($/1K)</th>
                    <th className="text-right pb-2 font-medium">Output ($/1K)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(pricing).map(([model, rates]: [string, any]) => (
                    <tr key={model} className="border-t" style={{ borderColor: "var(--dt-colors-border-default)" }}>
                      <td className="py-1.5">{model}</td>
                      <td className="py-1.5 text-right font-mono">${rates.input_per_1k?.toFixed(5)}</td>
                      <td className="py-1.5 text-right font-mono">${rates.output_per_1k?.toFixed(5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
