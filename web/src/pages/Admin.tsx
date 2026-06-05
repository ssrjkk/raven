import { useState, useEffect, useRef } from "react";
import { api, ChannelInfo } from "../api/client";
import { useToast } from "../components/Toast";

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

export default function Admin() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [audit, setAudit] = useState<AuditResult[]>([]);
  const [runningAudit, setRunningAudit] = useState(false);
  const [modelKey, setModelKey] = useState("");
  const [keyFeedback, setKeyFeedback] = useState<{ok: boolean; msg: string} | null>(null);
  const [channelsLoading, setChannelsLoading] = useState(true);
  const logEnd = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  useEffect(() => {
    api.channels().then(setChannels).catch(() => toast("Failed to load channels", "error"))
      .finally(() => setChannelsLoading(false));
    const interval = setInterval(() => {
      api.channels().then(setChannels).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    const es = new EventSource("/api/admin/logs/stream");
    es.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data);
        if (entry.message !== "heartbeat") {
          setLogs((prev) => [...prev.slice(-99), entry]);
        }
      } catch {}
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
      const res = await fetch("/api/admin/security/audit");
      if (res.ok) {
        const data = await res.json();
        setAudit(data.checks || []);
        toast("Security audit complete", "success");
      } else {
        toast("Audit failed", "error");
      }
    } catch {
      toast("Audit request failed", "error");
    }
    setRunningAudit(false);
  }

  async function updateModelKey() {
    setKeyFeedback(null);
    try {
      const res = await fetch("/api/admin/config/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Admin</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Channels</h2>
          {channelsLoading ? (
            <div className="space-y-2 animate-pulse">
              {[1, 2, 3].map((i) => <div key={i} className="h-10 bg-gray-800/50 rounded-lg" />)}
            </div>
          ) : (
            <div className="space-y-2">
              {channels.map((ch) => (
                <div key={ch.id} className="flex items-center justify-between py-2 px-3 bg-gray-800/30 rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${ch.ready ? "bg-green-400" : "bg-red-400"}`} />
                    <span className="text-sm text-gray-200">{ch.id}</span>
                    <span className="text-[10px] text-gray-500">{ch.type}</span>
                  </div>
                  <span className="text-xs text-gray-500">
                    sent:{ch.stats?.sent ?? 0} failed:{ch.stats?.failed ?? 0}
                  </span>
                </div>
              ))}
              {channels.length === 0 && <p className="text-sm text-gray-500">No channels registered</p>}
            </div>
          )}
        </div>

        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Model Configuration</h2>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">OpenRouter API Key</label>
              <input
                type="password"
                value={modelKey}
                onChange={(e) => setModelKey(e.target.value)}
                placeholder="sk-or-v1-..."
                className="w-full bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50"
              />
            </div>
            <button onClick={updateModelKey}
              className="bg-violet-700 hover:bg-violet-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium transition">
              Update Key
            </button>
            {keyFeedback && (
              <p className={`text-xs mt-1 ${keyFeedback.ok ? "text-green-400" : "text-red-400"}`}>
                {keyFeedback.msg}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-300">Security Audit</h2>
          <button onClick={runAudit} disabled={runningAudit}
            className="bg-amber-700 hover:bg-amber-600 disabled:bg-amber-900/50 text-white px-4 py-1.5 rounded-lg text-xs font-medium transition">
            {runningAudit ? "Running..." : "Run Audit"}
          </button>
        </div>
        {audit.length > 0 && (
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {audit.map((c, i) => (
              <div key={i} className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${
                c.passed ? "bg-green-900/10 text-green-300" : "bg-red-900/10 text-red-300"
              }`}>
                <span className="mt-0.5">{c.passed ? "✓" : "✗"}</span>
                <div className="flex-1">
                  <span className="font-medium">{c.check}</span>
                  {!c.passed && (
                    <p className="text-gray-500 mt-0.5">{c.fix_hint}</p>
                  )}
                </div>
                <span className={`text-[10px] uppercase ${c.severity === "high" ? "text-red-400" : "text-yellow-400"}`}>
                  {c.severity}
                </span>
              </div>
            ))}
          </div>
        )}
        {audit.length === 0 && !runningAudit && (
          <p className="text-sm text-gray-500">Run a security audit to check your configuration.</p>
        )}
      </div>

      <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Live Logs</h2>
        <div className="bg-black/40 rounded-lg p-3 h-48 overflow-y-auto font-mono text-xs space-y-1">
          {logs.length === 0 && <p className="text-gray-600">Waiting for logs...</p>}
          {logs.map((l, i) => (
            <div key={i} className={`${
              l.level === "ERROR" ? "text-red-400" :
              l.level === "WARNING" ? "text-yellow-400" :
              "text-gray-400"
            }`}>
              <span className="text-gray-600">{l.timestamp}</span> {l.level} {l.message}
            </div>
          ))}
          <div ref={logEnd} />
        </div>
      </div>
    </div>
  );
}