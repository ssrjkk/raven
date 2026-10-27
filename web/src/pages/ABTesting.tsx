import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { ABTestData, ABTestResults } from "../api/types";
import PageHeader from "../components/PageHeader";
import { useApiQuery } from "../hooks/useApiQuery";

export default function ABTesting() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<ABTestData | null>(null);
  const [results, setResults] = useState<ABTestResults | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [variantsJson, setVariantsJson] = useState('[{"name":"Control","weight":0.5,"is_control":true,"config":{}},{"name":"Variant","weight":0.5,"config":{}}]');
  const [metricName, setMetricName] = useState("conversion");
  const [metricType, setMetricType] = useState("rate");

  const { data: experimentsData, refetch: refetchExperiments } = useApiQuery<{ experiments: ABTestData[] }>(["abExperiments"], () => api.abExperiments());
  const experiments = experimentsData?.experiments ?? [];

  const createExperiment = useMutation({
    mutationFn: () => api.abCreate(name, desc, variantsJson, metricName, metricType),
    onSuccess: (r) => {
      setMsg(`Experiment created: ${r.name} (${r.id})`);
      setName(""); setDesc(""); setVariantsJson('[{"name":"Control","weight":0.5,"is_control":true,"config":{}},{"name":"Variant","weight":0.5,"config":{}}]');
      setMetricName("conversion"); setMetricType("rate");
      qc.invalidateQueries({ queryKey: ["abExperiments"] });
    },
    onError: (e: any) => setError(e.message),
  });

  async function selectExperiment(id: string) {
    setError(""); setResults(null);
    try {
      const [exp, res] = await Promise.all([
        api.abGet(id),
        api.abResults(id),
      ]);
      setSelected(exp);
      setResults(res);
    } catch (e: any) {
      setError(e.message);
    }
  }

  const changeStatus = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => api.abStatus(id, action),
    onSuccess: async (_data, { id, action }) => {
      setMsg(`Status changed to ${action}`);
      qc.invalidateQueries({ queryKey: ["abExperiments"] });
      try {
        const [exp, res] = await Promise.all([api.abGet(id), api.abResults(id)]);
        setSelected(exp);
        setResults(res);
      } catch (e) {
        console.error("Failed to refresh experiment after status change", e);
      }
    },
    onError: (e: any) => setError(e.message),
  });

  const deleteExperiment = useMutation({
    mutationFn: (id: string) => api.abDelete(id),
    onSuccess: (_data, id) => {
      setMsg("Experiment deleted");
      if (selected?.id === id) { setSelected(null); setResults(null); }
      qc.invalidateQueries({ queryKey: ["abExperiments"] });
    },
    onError: (e: any) => setError(e.message),
  });

  const statusColor = (s: string) => {
    switch (s) {
      case "running": return "var(--dt-colors-success-default)";
      case "paused": return "var(--dt-colors-warning-default)";
      case "completed": return "var(--dt-colors-accent-default)";
      default: return "var(--dt-colors-text-tertiary)";
    }
  };

  const statusBadge = (s: string) => {
    switch (s) {
      case "running": return "badge badge-success";
      case "paused": return "badge badge-warning";
      case "completed": return "badge badge-accent";
      default: return "badge badge-info";
    }
  };

  return (
    <div>
      <PageHeader title="A/B Testing" subtitle="Create and run split experiments" />

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">Create Experiment</h2>
            <div className="space-y-2 mb-3">
              <input placeholder="Experiment name" value={name} onChange={e => setName(e.target.value)}
                className="input-base" />
              <input placeholder="Description" value={desc} onChange={e => setDesc(e.target.value)}
                className="input-base" />
              <textarea placeholder='[{"name":"A","weight":0.5,"config":{}},...]' value={variantsJson} onChange={e => setVariantsJson(e.target.value)}
                rows={3} className="input-base font-mono" />
              <input placeholder="Metric name (default: conversion)" value={metricName} onChange={e => setMetricName(e.target.value)}
                className="input-base" />
              <select value={metricType} onChange={e => setMetricType(e.target.value)} className="input-base">
                <option value="rate">rate — per-unit outcome in 0..1 (two-proportion z-test)</option>
                <option value="mean">mean — per-unit value, e.g. latency (Welch t-test)</option>
              </select>
            </div>
            <button onClick={() => createExperiment.mutate()} disabled={createExperiment.isPending || !name || !desc}
              className="btn-primary">
              Create
            </button>
          </div>

          <div className="card">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Experiments ({experiments.length})</h2>
              <button onClick={() => refetchExperiments()} className="btn-ghost">
                Refresh
              </button>
            </div>
            {experiments.length === 0 ? (
              <p className="text-sm text-tertiary">No experiments yet.</p>
            ) : (
              <div className="space-y-2">
                {experiments.map((e) => (
                  <div key={e.id}
                    onClick={() => selectExperiment(e.id)}
                    className="p-2 rounded-lg text-sm cursor-pointer transition"
                    style={{ backgroundColor: selected?.id === e.id ? "var(--dt-colors-bg-tertiary)" : "transparent", border: selected?.id === e.id ? "1px solid var(--dt-colors-accent-subtle)" : "1px solid transparent" }}>
                    <div className="flex justify-between items-center">
                      <span className="font-medium">{e.name}</span>
                      <span className="text-xs" style={{ color: statusColor(e.status) }}>{e.status}</span>
                    </div>
                    <div className="text-xs mt-1 text-tertiary">
                      {e.variants?.map((v) => v.name).join(" vs ")} | {e.metric}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {selected && (
            <>
              <div className="card">
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.name}</h2>
                    <p className="text-sm text-secondary">{selected.description}</p>
                  </div>
                  <span className={statusBadge(selected.status)}>
                    {selected.status}
                  </span>
                </div>
                <div className="flex gap-2 mb-3">
                  {selected.status === "draft" && (
                    <button onClick={() => changeStatus.mutate({ id: selected.id, action: "running" })} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "var(--dt-colors-success-default)", color: "var(--dt-colors-text-on-accent)" }}>
                      Start
                    </button>
                  )}
                  {selected.status === "running" && (
                    <button onClick={() => changeStatus.mutate({ id: selected.id, action: "paused" })} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "var(--dt-colors-warning-default)", color: "var(--dt-colors-text-on-accent)" }}>
                      Pause
                    </button>
                  )}
                  {(selected.status === "running" || selected.status === "paused") && (
                    <button onClick={() => changeStatus.mutate({ id: selected.id, action: "completed" })} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-accent on-accent">
                      Complete
                    </button>
                  )}
                  <button onClick={() => deleteExperiment.mutate(selected.id)} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-danger-subtle text-danger">
                    Delete
                  </button>
                </div>
                <div className="text-sm space-y-1 text-secondary">
                  <p>Metric: <span className="font-medium">{selected.metric}</span> ({selected.metric_type})</p>
                  <p>Variants: {(() => {
                    const total = (selected.variants ?? []).reduce((s, v) => s + (v.weight || 0), 0) || 1;
                    return (selected.variants ?? []).map((v) => `${v.name} (${((v.weight / total) * 100).toFixed(1)}%)${v.is_control ? " [control]" : ""}`).join(", ");
                  })()}</p>
                </div>
              </div>

              {results && (
                <div className="card">
                  <h2 className="text-lg font-semibold mb-3">Results</h2>
                  <div className="grid grid-cols-2 gap-4 mb-4">
                    <div className="stat-card text-center">
                      <div className="stat-card-value">
                        {Object.values(results.unit_counts ?? {}).reduce((s, n) => s + n, 0)}
                      </div>
                      <div className="stat-card-label">Units (sample size)</div>
                    </div>
                    <div className="stat-card text-center">
                      <div className="stat-card-value">{results.total_events}</div>
                      <div className="stat-card-label">Events analyzed</div>
                    </div>
                  </div>

                  {results.comparisons?.length === 0 && (
                    <p className="text-sm text-tertiary mb-3">No comparison yet — every arm needs at least 2 units.</p>
                  )}

                  <div className="space-y-2 mb-3">
                    {results.comparisons?.map((c) => {
                      const lift = c.lift === null ? "undefined (control mean is 0)" : `${c.lift > 0 ? "+" : ""}${c.lift.toFixed(2)}%`;
                      return (
                        <div key={c.variant} className="p-3 rounded-lg bg-tertiary">
                          <div className="flex justify-between items-center">
                            <span className="font-medium">{c.variant} <span className="text-xs text-tertiary">vs {c.control}</span></span>
                            <span className={`text-sm ${c.significant ? "text-success" : "text-tertiary"}`}>
                              {c.significant ? `significant (p_adj ${c.p_adjusted.toExponential(2)})` : `not significant (p_adj ${c.p_adjusted.toFixed(3)})`}
                            </span>
                          </div>
                          <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-tertiary">
                            <span>Absolute diff: {c.diff >= 0 ? "+" : ""}{c.diff.toPrecision(4)}</span>
                            <span>95% CI: [{c.diff_ci_low.toPrecision(3)}, {c.diff_ci_high.toPrecision(3)}]</span>
                            <span>Relative lift: {lift}</span>
                            <span>p (raw): {c.p_value.toExponential(2)} · test: {c.test}</span>
                            <span>Units: {c.units} vs {c.control_units}</span>
                            <span>Mean: {c.mean.toPrecision(4)} vs {c.control_mean.toPrecision(4)}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="space-y-2">
                    {results.variants?.map((v) => (
                      <div key={v.name} className="p-3 rounded-lg bg-tertiary">
                        <div className="flex justify-between items-center">
                          <span className="font-medium">{v.name}{v.is_control ? " [control]" : ""}</span>
                          <span className={`text-sm ${v.lift === null ? "text-tertiary" : v.lift > 0 ? "text-success" : v.lift < 0 ? "text-danger" : ""}`}>
                            {v.is_control ? "baseline" : v.lift === null ? "lift undefined" : `${v.lift > 0 ? "+" : ""}${v.lift.toFixed(2)}%`}
                          </span>
                        </div>
                        <div className="grid grid-cols-4 gap-2 mt-2 text-xs text-tertiary">
                          <span>Units: {v.sample_count}</span>
                          <span>Events: {v.events}</span>
                          <span>Unit avg: {v.unit_avg}</span>
                          <span>No unit: {v.unattributed_events}</span>
                        </div>
                      </div>
                    ))}
                  </div>

                  {(results.srm?.imbalanced || (results.warnings?.length ?? 0) > 0 || results.events_dropped > 0 || results.events_orphaned > 0) && (
                    <div className="mt-3 p-3 rounded-lg text-xs space-y-1" style={{ background: "var(--dt-colors-status-warning-bg)" }}>
                      {results.srm?.imbalanced && (
                        <p className="text-danger">Sample ratio mismatch: the split itself is broken (χ² {results.srm.chi2.toFixed(2)}, p {results.srm.p_value.toExponential(2)}) — read no comparison from this experiment.</p>
                      )}
                      {(results.warnings ?? []).map((w) => <p key={w} className="text-secondary">{w}</p>)}
                      {results.events_dropped > 0 && <p className="text-danger">{results.events_dropped} events were dropped by the storage cap.</p>}
                      {results.events_orphaned > 0 && <p className="text-danger">{results.events_orphaned} events belong to removed variants and were excluded.</p>}
                    </div>
                  )}

                  <p className="text-xs text-tertiary mt-3">
                    {results.method} · α {results.alpha} · {results.multiplicity} across {results.comparisons?.length ?? 0} comparison(s).
                    Sample size is the number of units, not events; events without a unit are counted but excluded.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
