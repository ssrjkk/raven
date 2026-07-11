import { useState, useEffect } from "react";
import { api } from "../api/client";

export default function ABTesting() {
  const [experiments, setExperiments] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [variantsJson, setVariantsJson] = useState('[{"name":"Control","weight":0.5,"config":{}},{"name":"Variant","weight":0.5,"config":{}}]');
  const [metricName, setMetricName] = useState("conversion");

  useEffect(() => { loadExperiments(); }, []);

  async function loadExperiments() {
    setLoading(true); setError("");
    try {
      const r: any = await api.abExperiments();
      setExperiments(r.experiments);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleCreate() {
    setMsg(""); setError(""); setLoading(true);
    try {
      const r: any = await api.abCreate(name, desc, variantsJson, metricName);
      setMsg(`Experiment created: ${r.name} (${r.id})`);
      setName(""); setDesc(""); setVariantsJson('[{"name":"Control","weight":0.5,"config":{}},{"name":"Variant","weight":0.5,"config":{}}]');
      setMetricName("conversion");
      loadExperiments();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function selectExperiment(id: string) {
    setError(""); setResults(null);
    try {
      const [exp, res]: [any, any] = await Promise.all([
        api.abGet(id),
        api.abResults(id),
      ]);
      setSelected(exp);
      setResults(res);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleStatus(action: string) {
    if (!selected) return;
    setError(""); setMsg("");
    try {
      await api.abStatus(selected.id, action);
      setMsg(`Status changed to ${action}`);
      selectExperiment(selected.id);
      loadExperiments();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleDelete(id: string) {
    setError(""); setMsg("");
    try {
      await api.abDelete(id);
      setMsg("Experiment deleted");
      setSelected(null);
      setResults(null);
      loadExperiments();
    } catch (e: any) {
      setError(e.message);
    }
  }

  const statusColor = (s: string) => {
    switch (s) {
      case "running": return "var(--dt-colors-success-default)";
      case "paused": return "var(--dt-colors-warning-default)";
      case "completed": return "var(--dt-colors-accent-default)";
      default: return "var(--dt-colors-text-tertiary)";
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">A/B Testing</h1>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Create Experiment</h2>
            <div className="space-y-2 mb-3">
              <input placeholder="Experiment name" value={name} onChange={e => setName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <input placeholder="Description" value={desc} onChange={e => setDesc(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <textarea placeholder='[{"name":"A","weight":0.5,"config":{}},...]' value={variantsJson} onChange={e => setVariantsJson(e.target.value)}
                rows={3} className="w-full px-3 py-2 rounded-lg text-sm font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <input placeholder="Metric name (default: conversion)" value={metricName} onChange={e => setMetricName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <button onClick={handleCreate} disabled={loading || !name || !desc}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              Create
            </button>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Experiments ({experiments.length})</h2>
              <button onClick={loadExperiments} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
                Refresh
              </button>
            </div>
            {experiments.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No experiments yet.</p>
            ) : (
              <div className="space-y-2">
                {experiments.map((e: any) => (
                  <div key={e.id}
                    onClick={() => selectExperiment(e.id)}
                    className="p-2 rounded-lg text-sm cursor-pointer transition"
                    style={{ backgroundColor: selected?.id === e.id ? "var(--dt-colors-bg-tertiary)" : "transparent", border: selected?.id === e.id ? "1px solid var(--dt-colors-accent-subtle)" : "1px solid transparent" }}>
                    <div className="flex justify-between items-center">
                      <span className="font-medium">{e.name}</span>
                      <span className="text-xs" style={{ color: statusColor(e.status) }}>{e.status}</span>
                    </div>
                    <div className="text-xs mt-1" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                      {e.variants?.map((v: any) => v.name).join(" vs ")} | {e.metric}
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
              <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.name}</h2>
                    <p className="text-sm" style={{ color: "var(--dt-colors-text-secondary)" }}>{selected.description}</p>
                  </div>
                  <span className="px-2 py-1 rounded text-xs font-medium" style={{ backgroundColor: statusColor(selected.status), color: "#fff" }}>
                    {selected.status}
                  </span>
                </div>
                <div className="flex gap-2 mb-3">
                  {selected.status === "draft" && (
                    <button onClick={() => handleStatus("running")} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "var(--dt-colors-success-default)", color: "#fff" }}>
                      Start
                    </button>
                  )}
                  {selected.status === "running" && (
                    <button onClick={() => handleStatus("paused")} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "var(--dt-colors-warning-default)", color: "#fff" }}>
                      Pause
                    </button>
                  )}
                  {(selected.status === "running" || selected.status === "paused") && (
                    <button onClick={() => handleStatus("completed")} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                      Complete
                    </button>
                  )}
                  <button onClick={() => handleDelete(selected.id)} className="px-3 py-1.5 rounded-lg text-xs font-medium" style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "var(--dt-colors-danger-default)" }}>
                    Delete
                  </button>
                </div>
                <div className="text-sm space-y-1" style={{ color: "var(--dt-colors-text-secondary)" }}>
                  <p>Metric: <span className="font-medium">{selected.metric}</span></p>
                  <p>Variants: {selected.variants?.map((v: any) => `${v.name} (${(v.weight * 100).toFixed(0)}%)`).join(", ")}</p>
                </div>
              </div>

              {results && (
                <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
                  <h2 className="text-lg font-semibold mb-3">Results</h2>
                  <div className="grid grid-cols-2 gap-4 mb-4">
                    <div className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                      <div className="text-2xl font-bold">{results.total_events}</div>
                      <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Total Events</div>
                    </div>
                    <div className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                      <div className="text-lg font-bold" style={{ color: results.significant ? "var(--dt-colors-success-default)" : "var(--dt-colors-text-tertiary)" }}>
                        {(results.significance * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                        {results.significant ? "Significant!" : "Confidence"}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {results.variants?.map((v: any) => (
                      <div key={v.name} className="p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                        <div className="flex justify-between items-center">
                          <span className="font-medium">{v.name}</span>
                          <span className={`text-sm ${v.lift > 0 ? "text-green-400" : v.lift < 0 ? "text-red-400" : ""}`}>
                            {v.lift > 0 ? "+" : ""}{v.lift}%
                          </span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 mt-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                          <span>Events: {v.events}</span>
                          <span>Avg: {v.avg_value}</span>
                          <span>Samples: {v.sample_count}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
