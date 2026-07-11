import { useState } from "react";
import { api } from "../api/client";

type Tab = "inject" | "experiment" | "history";

const FAULT_TYPES = ["service_kill", "network_latency", "disk_fill", "cpu_storm", "memory_leak", "process_kill"];

export default function Chaos() {
  const [tab, setTab] = useState<Tab>("inject");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  // inject
  const [faultType, setFaultType] = useState(FAULT_TYPES[0]);
  const [target, setTarget] = useState("");
  const [duration, setDuration] = useState(30);
  const [intensity, setIntensity] = useState(0.5);
  const [activeFaults, setActiveFaults] = useState<any[]>([]);

  // experiment
  const [expName, setExpName] = useState("");
  const [faultsJson, setFaultsJson] = useState('[{"fault_type":"cpu_storm","duration_sec":10}]');
  const [hypothesis, setHypothesis] = useState("");
  const [expResult, setExpResult] = useState<any>(null);

  // history
  const [history, setHistory] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);

  async function handleInject() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.chaosInject(faultType, target, duration, intensity);
      setMsg(`Fault injected [${r.id}]`);
      loadActive();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleRecover(faultId: string) {
    setMsg(""); setError("");
    setLoading(true);
    try {
      await api.chaosRecover(faultId);
      setMsg(`Fault ${faultId} recovered`);
      loadActive();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleRecoverAll() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.chaosRecoverAll();
      setMsg(`Recovered ${r.recovered} faults`);
      loadActive();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function loadActive() {
    try {
      const r = await api.chaosActive();
      setActiveFaults(r.active);
    } catch { /* ignore */ }
  }

  async function loadHistory() {
    setLoading(true); setError("");
    try {
      const r = await api.chaosHistory();
      setHistory(r.history);
      const s = await api.chaosSummary();
      setSummary(s);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleRunExperiment() {
    setExpResult(null); setMsg(""); setError("");
    setLoading(true);
    try {
      const r = await api.chaosRunExperiment(expName, faultsJson, hypothesis);
      setExpResult(r);
      setMsg(`Experiment '${expName}' completed`);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "inject", label: "Inject Faults" },
    { key: "experiment", label: "Experiments" },
    { key: "history", label: "History" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Chaos Engineering</h1>

      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); if (t.key === "inject") loadActive(); if (t.key === "history") loadHistory(); }}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {tab === "inject" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Inject Fault</h2>
            <div className="space-y-3 mb-3">
              <select value={faultType} onChange={e => setFaultType(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}>
                {FAULT_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
              </select>
              <input placeholder="Target (service/process name)" value={target} onChange={e => setTarget(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Duration (s)</label>
                  <input type="number" min={1} value={duration} onChange={e => setDuration(parseFloat(e.target.value) || 30)}
                    className="w-full px-3 py-2 rounded-lg text-sm mt-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                </div>
                <div>
                  <label className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Intensity (0-1)</label>
                  <input type="number" min={0} max={1} step={0.1} value={intensity} onChange={e => setIntensity(parseFloat(e.target.value) || 0.5)}
                    className="w-full px-3 py-2 rounded-lg text-sm mt-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={handleInject} disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Inject
              </button>
              <button onClick={handleRecoverAll} disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "var(--dt-colors-danger-default)" }}>
                Recover All
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Active Faults ({activeFaults.length})</h2>
              <button onClick={loadActive} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
                Refresh
              </button>
            </div>
            {activeFaults.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No active faults.</p>
            ) : (
              <div className="space-y-2">
                {activeFaults.map((f: any) => (
                  <div key={f.id} className="flex items-center justify-between p-2 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    <div className="text-sm">
                      <span className="font-medium">{f.config?.fault_type}</span>
                      <span className="ml-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{f.config?.target || "system"}</span>
                    </div>
                    <button onClick={() => handleRecover(f.id)} className="px-2 py-1 rounded text-xs" style={{ backgroundColor: "rgba(34,197,94,0.15)", color: "var(--dt-colors-success-default)" }}>
                      Recover
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "experiment" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Run Experiment</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="Experiment name" value={expName} onChange={e => setExpName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <textarea placeholder='[{"fault_type":"cpu_storm","duration_sec":10}]' value={faultsJson} onChange={e => setFaultsJson(e.target.value)}
                rows={4} className="w-full px-3 py-2 rounded-lg text-sm font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <input placeholder="Hypothesis (optional)" value={hypothesis} onChange={e => setHypothesis(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <button onClick={handleRunExperiment} disabled={loading || !expName || !faultsJson}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              {loading ? "Running..." : "Run Experiment"}
            </button>
          </div>

          {expResult && (
            <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <h2 className="text-lg font-semibold mb-3">Experiment Result</h2>
              <div className="space-y-2 text-sm">
                <p>Status: <span className="font-medium">{expResult.status}</span></p>
                <p>Resilience: <span className="font-medium">{expResult.resilience_score?.toFixed(4)}</span></p>
                <p>Hypothesis validated: <span className="font-medium">{expResult.hypothesis_validated ? "✓" : "✗"}</span></p>
                <p>Faults injected: {expResult.faults_injected}</p>
                <p>Faults recovered: {expResult.faults_recovered}</p>
                <p>Experiment ID: <code className="text-xs">{expResult.experiment_id}</code></p>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "history" && (
        <div className="space-y-6">
          {summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Experiments", value: summary.experiments_run },
                { label: "Avg Resilience", value: summary.avg_resilience?.toFixed(4) },
                { label: "Avg Steadiness", value: summary.avg_steadiness?.toFixed(4) },
                { label: "Hypotheses Validated", value: summary.hypotheses_validated },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-xl font-bold">{s.value ?? "—"}</div>
                  <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.label}</div>
                </div>
              ))}
            </div>
          )}

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Fault History ({history.length})</h2>
            {history.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No faults injected yet.</p>
            ) : (
              <div className="space-y-2">
                {history.map((h: any) => (
                  <div key={h.id} className="p-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    <span className="font-medium">{h.config?.fault_type}</span>
                    <span className="ml-2">{h.config?.target || "system"}</span>
                    <span className="ml-2 text-xs">{h.recovered ? "✓ recovered" : "⚠ active"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
