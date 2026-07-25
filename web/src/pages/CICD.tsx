import { useMutation } from "@tanstack/react-query";
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
  const [tab, setTab] = useState<"workflows" | "runs" | "status" | "trigger">("workflows");

  const loadWorkflows = useMutation({
    mutationFn: () => api.cicdWorkflows(owner, repo, provider),
    onSuccess: (r) => { setResult(r.text); setError(""); },
    onError: (e: any) => setError(e.message || "Failed to list workflows"),
  });

  const loadRuns = useMutation({
    mutationFn: () => api.cicdRuns(owner, repo, branch, statusFilter, provider),
    onSuccess: (r) => { setResult(r.text); setError(""); },
    onError: (e: any) => setError(e.message || "Failed to list runs"),
  });

  const loadStatus = useMutation({
    mutationFn: () => {
      if (!pipelineId) throw new Error("Pipeline ID required");
      return api.cicdStatus(pipelineId, owner, repo, provider);
    },
    onSuccess: (r) => { setResult(r.text); setError(""); },
    onError: (e: any) => setError(e.message || "Failed to check status"),
  });

  const triggerRun = useMutation({
    mutationFn: () => {
      if (!workflowId) throw new Error("Workflow ID required");
      return api.cicdRun(workflowId, owner, repo, ref, inputs, provider);
    },
    onSuccess: (r) => { setResult(r.text); setError(""); },
    onError: (e: any) => setError(e.message || "Failed to trigger run"),
  });

  const btn = { backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" };
  const inp: React.CSSProperties = {
    backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)",
    color: "var(--dt-colors-text-primary)", padding: "8px 12px", borderRadius: "6px",
    border: "1px solid", fontSize: "14px", boxSizing: "border-box",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-primary">CI/CD</h1>
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
        <div className="px-4 py-2 rounded text-sm bg-danger-subtle text-danger">
          {error}
          <button onClick={() => setError("")} className="ml-3 text-xs text-tertiary">dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
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
          <button onClick={() => loadWorkflows.mutate()} disabled={loadWorkflows.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
            {loadWorkflows.isPending ? "Loading..." : "List Workflows"}
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
            <button onClick={() => loadRuns.mutate()} disabled={loadRuns.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
              {loadRuns.isPending ? "Loading..." : "List Runs"}
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
              onKeyDown={(e) => e.key === "Enter" && loadStatus.mutate()} />
            <button onClick={() => loadStatus.mutate()} disabled={loadStatus.isPending || !pipelineId}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
              {loadStatus.isPending ? "Loading..." : "Check Status"}
            </button>
          </div>
        </div>
      )}

      {tab === "trigger" && (
        <div className="space-y-3 max-w-lg">
          <p className="text-sm text-tertiary">
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
          <button onClick={() => triggerRun.mutate()} disabled={triggerRun.isPending || !workflowId}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40" style={btn}>
            {triggerRun.isPending ? "Triggering..." : "Trigger Workflow"}
          </button>
        </div>
      )}

      {result && (
        <pre className="p-4 rounded text-sm whitespace-pre-wrap bg-secondary text-primary">
          {result}
        </pre>
      )}
    </div>
  );
}
