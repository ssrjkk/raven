import { useState } from "react";
import { api } from "../api/client";

export default function CICD() {
  const [owner, setOwner] = useState("");
  const [repo, setRepo] = useState("");
  const [provider, setProvider] = useState("github");
  const [workflowId, setWorkflowId] = useState("");
  const [pipelineId, setPipelineId] = useState("");
  const [ref, setRef] = useState("main");
  const [inputs, setInputs] = useState("");
  const [branch, setBranch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"workflows" | "runs" | "status" | "trigger">("workflows");

  async function loadWorkflows() {
    setLoading(true); setError(""); setResult("");
    try { const r = await api.cicdWorkflows(owner, repo, provider); setResult(r.text); }
    catch (e: any) { setError(e.message || "Failed to list workflows"); }
    finally { setLoading(false); }
  }

  async function loadRuns() {
    setLoading(true); setError(""); setResult("");
    try { const r = await api.cicdRuns(owner, repo, branch, statusFilter, provider); setResult(r.text); }
    catch (e: any) { setError(e.message || "Failed to list runs"); }
    finally { setLoading(false); }
  }

  async function loadStatus() {
    if (!pipelineId) return;
    setLoading(true); setError(""); setResult("");
    try { const r = await api.cicdStatus(pipelineId, owner, repo, provider); setResult(r.text); }
    catch (e: any) { setError(e.message || "Failed to check status"); }
    finally { setLoading(false); }
  }

  async function triggerRun() {
    if (!workflowId) return;
    setLoading(true); setError(""); setResult("");
    try { const r = await api.cicdRun(workflowId, owner, repo, ref, inputs, provider); setResult(r.text); }
    catch (e: any) { setError(e.message || "Failed to trigger run"); }
    finally { setLoading(false); }
  }

  const btn = { backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" };
  const inp: React.CSSProperties = {
    backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)",
    color: "var(--dt-colors-text-primary)", padding: "8px 12px", borderRadius: "6px",
    border: "1px solid", fontSize: "14px", boxSizing: "border-box",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: "var(--dt-colors-text-primary)" }}>CI/CD</h1>
        <div className="flex items-center gap-2">
          <select style={inp} value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="github">GitHub Actions</option>
            <option value="gitlab">GitLab CI</option>
          </select>
          <input style={inp} placeholder="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
          <input style={inp} placeholder="Repo / Project ID" value={repo} onChange={(e) => setRepo(e.target.value)} />
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 rounded text-sm" style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "#ef4444" }}>
          {error}
          <button onClick={() => setError("")} className="ml-3 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["workflows", "runs", "status", "trigger"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className="px-4 py-2 text-sm font-medium transition rounded-t"
            style={{
              color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderBottom: tab === t ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent",
            }}>
            {t === "trigger" ? "Trigger Run" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "workflows" && (
        <div className="space-y-3">
          <button onClick={loadWorkflows} disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
            {loading ? "Loading..." : "List Workflows"}
          </button>
        </div>
      )}

      {tab === "runs" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input style={inp} placeholder="Branch filter" value={branch} onChange={(e) => setBranch(e.target.value)} />
            <select style={inp} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="in_progress">In Progress</option>
              <option value="queued">Queued</option>
            </select>
            <button onClick={loadRuns} disabled={loading}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
              {loading ? "Loading..." : "List Runs"}
            </button>
          </div>
        </div>
      )}

      {tab === "status" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input style={{ ...inp, flex: 1 }}
              placeholder="Pipeline / Run ID" value={pipelineId}
              onChange={(e) => setPipelineId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadStatus()} />
            <button onClick={loadStatus} disabled={loading || !pipelineId}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
              {loading ? "Loading..." : "Check Status"}
            </button>
          </div>
        </div>
      )}

      {tab === "trigger" && (
        <div className="space-y-3 max-w-lg">
          <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            Owner: <strong>{owner || "(not set)"}</strong> &middot; Repo: <strong>{repo || "(not set)"}</strong>
          </p>
          <input style={{ ...inp, width: "100%" }}
            placeholder="Workflow ID or filename" value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
          />
          <input style={{ ...inp, width: "100%" }}
            placeholder="Ref (branch/tag, default: main)" value={ref}
            onChange={(e) => setRef(e.target.value)}
          />
          <textarea style={{ ...inp, width: "100%" }}
            placeholder="Workflow inputs (JSON, optional)" rows={4}
            value={inputs} onChange={(e) => setInputs(e.target.value)}
          />
          <button onClick={triggerRun} disabled={loading || !workflowId}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
            {loading ? "Triggering..." : "Trigger Workflow"}
          </button>
        </div>
      )}

      {result && (
        <pre className="p-4 rounded text-sm whitespace-pre-wrap" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-primary)" }}>
          {result}
        </pre>
      )}
    </div>
  );
}
