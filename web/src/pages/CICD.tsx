import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="CI/CD"
        subtitle="Inspect and trigger pipelines across providers"
        actions={
          <>
            <select className="input-base px-3 py-2 text-sm" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="github">GitHub Actions</option>
              <option value="gitlab">GitLab CI</option>
            </select>
            <input className="input-base px-3 py-2 text-sm" placeholder="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
            <input className="input-base px-3 py-2 text-sm" placeholder="Repo / Project ID" value={repo} onChange={(e) => setRepo(e.target.value)} />
          </>
        }
      />

      {error && (
        <div className="px-4 py-2 rounded text-sm bg-danger-subtle text-danger">
          {error}
          <button onClick={() => setError("")} className="ml-3 text-xs text-tertiary">dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
        {(["workflows", "runs", "status", "trigger"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "tab-active" : "tab-inactive"}`}
          >
            {t === "trigger" ? "Trigger Run" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "workflows" && (
        <div className="space-y-3">
          <button onClick={() => loadWorkflows.mutate()} disabled={loadWorkflows.isPending} className="btn-primary">
            {loadWorkflows.isPending ? "Loading..." : "List Workflows"}
          </button>
        </div>
      )}

      {tab === "runs" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input className="input-base px-3 py-2 text-sm" placeholder="Branch filter" value={branch} onChange={(e) => setBranch(e.target.value)} />
            <select className="input-base px-3 py-2 text-sm" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="in_progress">In Progress</option>
              <option value="queued">Queued</option>
            </select>
            <button onClick={() => loadRuns.mutate()} disabled={loadRuns.isPending} className="btn-primary">
              {loadRuns.isPending ? "Loading..." : "List Runs"}
            </button>
          </div>
        </div>
      )}

      {tab === "status" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input
              className="input-base flex-1 px-3 py-2 text-sm"
              placeholder="Pipeline / Run ID"
              value={pipelineId}
              onChange={(e) => setPipelineId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadStatus.mutate()}
            />
            <button onClick={() => loadStatus.mutate()} disabled={loadStatus.isPending || !pipelineId} className="btn-primary">
              {loadStatus.isPending ? "Loading..." : "Check Status"}
            </button>
          </div>
        </div>
      )}

      {tab === "trigger" && (
        <div className="card space-y-3 max-w-lg">
          <p className="text-sm text-tertiary">
            Owner: <strong>{owner || "(not set)"}</strong> &middot; Repo: <strong>{repo || "(not set)"}</strong>
          </p>
          <input
            className="input-base w-full"
            placeholder="Workflow ID or filename"
            value={workflowId}
            onChange={(e) => setWorkflowId(e.target.value)}
          />
          <input
            className="input-base w-full"
            placeholder="Ref (branch/tag, default: main)"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
          />
          <textarea
            className="input-base w-full"
            placeholder="Workflow inputs (JSON, optional)"
            rows={4}
            value={inputs}
            onChange={(e) => setInputs(e.target.value)}
          />
          <button onClick={() => triggerRun.mutate()} disabled={triggerRun.isPending || !workflowId} className="btn-primary">
            {triggerRun.isPending ? "Triggering..." : "Trigger Workflow"}
          </button>
        </div>
      )}

      {result && (
        <pre className="p-4 rounded text-sm whitespace-pre-wrap bg-secondary text-primary border border-default">
          {result}
        </pre>
      )}
    </div>
  );
}
