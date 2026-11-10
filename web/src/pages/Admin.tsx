import { useEffect, useRef, useState } from "react";

import { api, type ChannelInfo, getToken } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
}

interface AuditResult {
  check: string;
  passed: boolean;
  severity: string;
  fix_hint: string;
}

interface ExperimentalModelStatus {
  ref: string;
  model: string;
  size_gb: number;
  ollama_reachable: boolean;
  present: boolean;
  is_default: boolean;
  default_model: string;
  env_file: string;
  hardware: { ram_total_gb: number; ram_free_gb: number; disk_free_gb: number; vram_mb: number };
  blockers: string[];
  warnings: string[];
  busy: boolean;
  error?: string;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function fetchExperimentalModel(): Promise<ExperimentalModelStatus> {
  const res = await fetch("/api/admin/models/experimental", { headers: authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function Admin() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [audit, setAudit] = useState<AuditResult[]>([]);
  const [runningAudit, setRunningAudit] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [keyFeedback, setKeyFeedback] = useState<{ok: boolean; msg: string} | null>(null);
  const [modelFeedback, setModelFeedback] = useState<{ok: boolean; msg: string} | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  const { data: channelsData, isLoading: channelsLoading } = useApiQuery<ChannelInfo[]>(["adminChannels"], () => api.channels(), { refetchInterval: 10000 });
  const channels = channelsData ?? [];

  const {
    data: model,
    refetch: refetchModel,
  } = useApiQuery<ExperimentalModelStatus>(["experimentalModel"], fetchExperimentalModel, {
    retry: false,
    // The pull is gigabytes and runs off the request loop; the screen follows it until it lands.
    refetchInterval: (q) => (q.state.data?.busy ? 2000 : false),
  });

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const url = `/api/admin/logs/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    es.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data);
        if (entry.message !== "heartbeat") {
          setLogs((prev) => [...prev.slice(-99), entry]);
        }
      } catch (e) { console.error("log parse error:", e); }
    };
    es.onerror = () => {
      toast("Log stream disconnected", "error");
    };
    return () => es.close();
  }, []);

  async function runAudit() {
    setRunningAudit(true);
    setAudit([]);
    try {
      const res = await fetch("/api/admin/security/audit", { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setAudit(data.checks || []);
        toast("Security audit complete", "success");
      } else {
        toast("Audit failed", "error");
      }
    } catch (e) { console.error("audit:", e);
      toast("Audit request failed", "error");
    }
    setRunningAudit(false);
  }

  async function updateModelKey() {
    setKeyFeedback(null);
    try {
      const res = await fetch("/api/admin/config/key", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ key: "openrouter_api_key", value: modelKey }),
      });
      if (res.ok) {
        setKeyFeedback({ ok: true, msg: "Key updated successfully" });
        toast("API key updated", "success");
      } else {
        const err = await res.text();
        setKeyFeedback({ ok: false, msg: `Update failed: ${err}` });
      }
    } catch (e) {
      setKeyFeedback({ ok: false, msg: `Network error: ${e}` });
      toast("Failed to update key", "error");
    }
  }

  async function switchModel(action: "enable" | "disable", force = false) {
    setModelFeedback(null);
    try {
      const res = await fetch("/api/admin/models/experimental", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ action, force }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setModelFeedback({ ok: false, msg: String(body.detail || body.error || `HTTP ${res.status}`) });
        toast(action === "enable" ? "Model switch refused" : "Revert failed", "error");
        return;
      }
      setModelFeedback({ ok: true, msg: String(body.detail || "") });
      toast(body.busy ? "Download started" : "Model switched", "success");
      await refetchModel();
    } catch (e) {
      setModelFeedback({ ok: false, msg: `Network error: ${e}` });
      toast("Model switch request failed", "error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Admin" subtitle="Channels, model configuration, security audit, and live logs" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-primary mb-3">Channels</h2>
          {channelsLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} height={40} rounded="lg" />)}
            </div>
          ) : (
            <div className="space-y-2">
              {channels.map((ch) => (
                <div key={ch.id} className="flex items-center justify-between py-2 px-3 bg-tertiary rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ch.ready ? "var(--dt-colors-status-success)" : "var(--dt-colors-status-error)" }} />
                    <span className="text-sm text-primary">{ch.id}</span>
                    <span className="text-[10px] text-tertiary">{ch.type}</span>
                  </div>
                  <span className="text-xs text-tertiary">
                    sent:{ch.stats?.sent ?? 0} failed:{ch.stats?.failed ?? 0}
                  </span>
                </div>
              ))}
              {channels.length === 0 && <p className="text-sm text-tertiary">No channels registered</p>}
            </div>
          )}
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold text-primary mb-3">Model Configuration</h2>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-tertiary block mb-1">OpenRouter API Key</label>
              <input
                type="password"
                value={modelKey}
                onChange={(e) => setModelKey(e.target.value)}
                placeholder="sk-or-v1-..."
                className="input-base"
              />
            </div>
            <button onClick={updateModelKey}
              className="btn-primary">
              Update Key
            </button>
            {keyFeedback && (
              <p className={`text-xs mt-1 ${keyFeedback.ok ? "text-success" : "text-danger"}`}>
                {keyFeedback.msg}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="card p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h2 className="text-sm font-semibold text-primary">Bundled free experimental model</h2>
            <p className="text-xs text-tertiary">
              Uncensored 9B served locally by Ollama — no API key, no hosted credit. Experimental: answers and refusal
              behaviour differ from the configured model.
            </p>
          </div>
          {model && (
            <span className={`badge shrink-0 ${model.is_default ? "badge-success" : "badge-warning"}`}>
              {model.busy ? "downloading" : model.is_default ? "in use" : "not in use"}
            </span>
          )}
        </div>

        {!model ? (
          <Skeleton height={140} rounded="lg" />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
              <div className="bg-tertiary rounded-lg px-3 py-2">
                <div className="text-tertiary mb-0.5">Ollama</div>
                <div className="text-primary">
                  {model.ollama_reachable ? "reachable" : "not reachable — start Ollama, then switch on"}
                </div>
              </div>
              <div className="bg-tertiary rounded-lg px-3 py-2">
                <div className="text-tertiary mb-0.5">Weights in Ollama</div>
                <div className="text-primary">
                  {model.present ? "pulled" : `not pulled (${model.size_gb.toFixed(2)} GB download)`}
                </div>
              </div>
              <div className="bg-tertiary rounded-lg px-3 py-2 min-w-0">
                <div className="text-tertiary mb-0.5">Default model</div>
                <div className="text-primary font-mono break-all">{model.default_model}</div>
              </div>
              <div className="bg-tertiary rounded-lg px-3 py-2 min-w-0">
                <div className="text-tertiary mb-0.5">This machine</div>
                <div className="text-primary">
                  {model.hardware.ram_free_gb.toFixed(1)} of {model.hardware.ram_total_gb.toFixed(1)} GB RAM free ·{" "}
                  {model.hardware.disk_free_gb.toFixed(1)} GB disk free ·{" "}
                  {model.hardware.vram_mb > 0 ? `${model.hardware.vram_mb} MB VRAM` : "no GPU (CPU inference)"}
                </div>
              </div>
            </div>

            <p className="text-[10px] text-tertiary font-mono break-all">{model.ref}</p>

            {model.blockers.map((b, i) => (
              <p key={`b${i}`} className="text-xs bg-danger-muted text-danger rounded-lg px-3 py-2">
                {b}
              </p>
            ))}
            {model.warnings.map((w, i) => (
              <p key={`w${i}`} className="text-xs bg-warning-muted text-warning rounded-lg px-3 py-2">
                {w}
              </p>
            ))}
            {model.error && (
              <p className="text-xs bg-danger-muted text-danger rounded-lg px-3 py-2">{model.error}</p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {!model.is_default && (
                <button
                  onClick={() => switchModel("enable")}
                  disabled={model.busy || model.blockers.length > 0}
                  className="btn-primary disabled:opacity-40"
                >
                  {model.busy ? "Downloading…" : `Switch on (${model.size_gb.toFixed(2)} GB first run)`}
                </button>
              )}
              {model.blockers.length > 0 && !model.busy && (
                <button
                  onClick={() => switchModel("enable", true)}
                  className="btn-outline disabled:opacity-40"
                  style={{ color: "var(--dt-colors-status-warning)", borderColor: "var(--dt-colors-status-warning)" }}
                >
                  Switch on anyway
                </button>
              )}
              {model.is_default && (
                <button onClick={() => switchModel("disable")} disabled={model.busy} className="btn-outline disabled:opacity-40">
                  Revert to previous model
                </button>
              )}
              <button onClick={() => refetchModel()} disabled={model.busy} className="btn-outline disabled:opacity-40">
                Refresh
              </button>
            </div>

            {modelFeedback && (
              <p className={`text-xs ${modelFeedback.ok ? "text-success" : "text-danger"}`}>{modelFeedback.msg}</p>
            )}
            <p className="text-[10px] text-tertiary">Written to {model.env_file}; a running gateway picks it up within 5 s.</p>
          </div>
        )}
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-primary">Security Audit</h2>
          <button onClick={runAudit} disabled={runningAudit}
            className="btn-outline disabled:opacity-40"
            style={{ color: "var(--dt-colors-status-warning)", borderColor: "var(--dt-colors-status-warning)" }}>
            {runningAudit ? "Running..." : "Run Audit"}
          </button>
        </div>
        {audit.length > 0 && (
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {audit.map((c, i) => (
              <div key={i} className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${
                c.passed ? "bg-success-muted text-success" : "bg-danger-muted text-danger"
              }`}>
                <span className="mt-0.5">{c.passed ? "✓" : "✗"}</span>
                <div className="flex-1">
                  <span className="font-medium">{c.check}</span>
                  {!c.passed && (
                    <p className="text-tertiary mt-0.5">{c.fix_hint}</p>
                  )}
                </div>
                <span className={`badge ${c.severity === "high" ? "badge-error" : "badge-warning"}`}>
                  {c.severity}
                </span>
              </div>
            ))}
          </div>
        )}
        {audit.length === 0 && !runningAudit && (
          <p className="text-sm text-tertiary">Run a security audit to check your configuration.</p>
        )}
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold text-primary mb-3">Live Logs</h2>
        <div className="bg-primary border border-default rounded-lg p-3 h-48 overflow-y-auto font-mono text-xs space-y-1">
          {logs.length === 0 && <p className="text-tertiary">Waiting for logs...</p>}
          {logs.map((l, i) => (
            <div key={i} className={`${
              l.level === "ERROR" ? "text-danger" :
              l.level === "WARNING" ? "text-warning" :
              "text-tertiary"
            }`}>
              <span className="text-tertiary">{l.timestamp}</span> {l.level} {l.message}
            </div>
          ))}
          <div ref={logEnd} />
        </div>
      </div>
    </div>
  );
}