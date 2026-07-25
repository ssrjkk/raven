import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

type Tab = "inject" | "experiment" | "history";

interface ChaosFaultConfig {
  fault_type: string;
  target?: string;
}

interface ChaosFault {
  id: string;
  config?: ChaosFaultConfig;
  recovered?: boolean;
}

interface ChaosExperimentResult {
  status: string;
  resilience_score?: number;
  hypothesis_validated?: boolean;
  faults_injected?: number;
  faults_recovered?: number;
  experiment_id?: string;
}

interface ChaosSummary {
  experiments_run: number;
  avg_resilience?: number;
  avg_steadiness?: number;
  hypotheses_validated?: number;
}

const FAULT_TYPES = ["service_kill", "network_latency", "disk_fill", "cpu_storm", "memory_leak", "process_kill"];

export default function Chaos() {
  const [tab, setTab] = useState<Tab>("inject");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // inject
  const [faultType, setFaultType] = useState(FAULT_TYPES[0]);
  const [target, setTarget] = useState("");
  const [duration, setDuration] = useState(30);
  const [intensity, setIntensity] = useState(0.5);
  const [activeFaults, setActiveFaults] = useState<ChaosFault[]>([]);

  // experiment
  const [expName, setExpName] = useState("");
  const [faultsJson, setFaultsJson] = useState('[{"fault_type":"cpu_storm","duration_sec":10}]');
  const [hypothesis, setHypothesis] = useState("");
  const [expResult, setExpResult] = useState<ChaosExperimentResult | null>(null);

  // history
  const [history, setHistory] = useState<ChaosFault[]>([]);
  const [summary, setSummary] = useState<ChaosSummary | null>(null);

  async function loadActive() {
    try {
      const r = await api.chaosActive();
      setActiveFaults(r.active);
    } catch (e) { console.error("chaos loadActive:", e); }
  }

  async function loadHistory() {
    try {
      const r = await api.chaosHistory();
      setHistory(r.history);
      const s = await api.chaosSummary();
      setSummary(s);
    } catch (e: any) {
      setError(e.message);
    }
  }

  const injectMutation = useMutation({
    mutationFn: () => api.chaosInject(faultType, target, duration, intensity),
    onSuccess: (r) => { setMsg(`Fault injected [${r.id}]`); setError(""); loadActive(); },
    onError: (e: any) => setError(e.message),
  });

  const recoverMutation = useMutation({
    mutationFn: (faultId: string) => api.chaosRecover(faultId),
    onSuccess: (_data, faultId) => { setMsg(`Fault ${faultId} recovered`); setError(""); loadActive(); },
    onError: (e: any) => setError(e.message),
  });

  const recoverAllMutation = useMutation({
    mutationFn: () => api.chaosRecoverAll(),
    onSuccess: (r) => { setMsg(`Recovered ${r.recovered} faults`); setError(""); loadActive(); },
    onError: (e: any) => setError(e.message),
  });

  const runExperimentMutation = useMutation({
    mutationFn: () => api.chaosRunExperiment(expName, faultsJson, hypothesis),
    onSuccess: (r) => { setExpResult(r); setMsg(`Experiment '${expName}' completed`); setError(""); },
    onError: (e: any) => setError(e.message),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "inject", label: "Inject Faults" },
    { key: "experiment", label: "Experiments" },
    { key: "history", label: "History" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Chaos Engineering</h1>

      <div className="flex gap-1 mb-6 border-b border-default">
        {tabs.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); if (t.key === "inject") loadActive(); if (t.key === "history") loadHistory(); }}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {tab === "inject" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Inject Fault</h2>
            <div className="space-y-3 mb-3">
              <select value={faultType} onChange={e => setFaultType(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default">
                {FAULT_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
              </select>
              <input placeholder="Target (service/process name)" value={target} onChange={e => setTarget(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-tertiary">Duration (s)</label>
                  <input type="number" min={1} value={duration} onChange={e => setDuration(parseFloat(e.target.value) || 30)}
                    className="w-full px-3 py-2 rounded-lg text-sm mt-1 bg-tertiary text-primary border-default" />
                </div>
                <div>
                  <label className="text-xs text-tertiary">Intensity (0-1)</label>
                  <input type="number" min={0} max={1} step={0.1} value={intensity} onChange={e => setIntensity(parseFloat(e.target.value) || 0.5)}
                    className="w-full px-3 py-2 rounded-lg text-sm mt-1 bg-tertiary text-primary border-default" />
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => injectMutation.mutate()} disabled={injectMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
                {injectMutation.isPending ? "Injecting..." : "Inject"}
              </button>
              <button onClick={() => recoverAllMutation.mutate()} disabled={recoverAllMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-danger-subtle text-danger">
                Recover All
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Active Faults ({activeFaults.length})</h2>
              <button onClick={loadActive} className="px-3 py-1 rounded-lg text-xs btn-secondary-text">
                Refresh
              </button>
            </div>
            {activeFaults.length === 0 ? (
              <p className="text-sm text-tertiary">No active faults.</p>
            ) : (
              <div className="space-y-2">
                {activeFaults.map((f) => (
                  <div key={f.id} className="flex items-center justify-between p-2 rounded-lg bg-tertiary">
                    <div className="text-sm">
                      <span className="font-medium">{f.config?.fault_type}</span>
                      <span className="ml-2 text-xs text-tertiary">{f.config?.target || "system"}</span>
                    </div>
                    <button onClick={() => recoverMutation.mutate(f.id)} className="px-2 py-1 rounded text-xs" style={{ backgroundColor: "rgba(34,197,94,0.15)", color: "var(--dt-colors-success-default)" }}>
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
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Run Experiment</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="Experiment name" value={expName} onChange={e => setExpName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <textarea placeholder='[{"fault_type":"cpu_storm","duration_sec":10}]' value={faultsJson} onChange={e => setFaultsJson(e.target.value)}
                rows={4} className="w-full px-3 py-2 rounded-lg text-sm font-mono bg-tertiary text-primary border-default" />
              <input placeholder="Hypothesis (optional)" value={hypothesis} onChange={e => setHypothesis(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            </div>
            <button onClick={() => runExperimentMutation.mutate()} disabled={runExperimentMutation.isPending || !expName || !faultsJson}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
              {runExperimentMutation.isPending ? "Running..." : "Run Experiment"}
            </button>
          </div>

          {expResult && (
            <div className="p-4 rounded-lg bg-secondary">
              <h2 className="text-lg font-semibold mb-3">Experiment Result</h2>
              <div className="space-y-2 text-sm">
                <p>Status: <span className="font-medium">{expResult.status}</span></p>
                <p>Resilience: <span className="font-medium">{expResult.resilience_score?.toFixed(4)}</span></p>
                <p>Hypothesis validated: <span className="font-medium">{expResult.hypothesis_validated ? "РІСљвЂњ" : "РІСљвЂ”"}</span></p>
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
                <div key={s.label} className="p-3 rounded-lg text-center bg-tertiary">
                  <div className="text-xl font-bold">{s.value ?? "РІР‚вЂќ"}</div>
                  <div className="text-xs text-tertiary">{s.label}</div>
                </div>
              ))}
            </div>
          )}

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Fault History ({history.length})</h2>
            {history.length === 0 ? (
              <p className="text-sm text-tertiary">No faults injected yet.</p>
            ) : (
              <div className="space-y-2">
                {history.map((h) => (
                  <div key={h.id} className="p-2 rounded-lg text-sm bg-tertiary">
                    <span className="font-medium">{h.config?.fault_type}</span>
                    <span className="ml-2">{h.config?.target || "system"}</span>
                    <span className="ml-2 text-xs">{h.recovered ? "РІСљвЂњ recovered" : "РІС™В  active"}</span>
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
