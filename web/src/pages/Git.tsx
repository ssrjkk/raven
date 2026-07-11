import { useEffect, useState } from "react";
import { api } from "../api/client";

interface CommitEntry {
  hash: string;
  message: string;
  author: string;
  date: string;
}

interface ReviewComment {
  file: string;
  line: number;
  severity: string;
  message: string;
}

export default function Git() {
  const [repo, setRepo] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [branches, setBranches] = useState<{ branches: string[]; current: string } | null>(null);
  const [log, setLog] = useState<CommitEntry[]>([]);
  const [diff, setDiff] = useState("");
  const [commitMsg, setCommitMsg] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [prBody, setPrBody] = useState("");
  const [reviewResult, setReviewResult] = useState<{ summary: string; comments: ReviewComment[] } | null>(null);
  const [newBranch, setNewBranch] = useState("");
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"status" | "log" | "diff" | "review" | "pr">("status");

  function refresh() {
    api.gitStatus(repo).then(setStatus);
    api.gitBranches(repo).then(setBranches);
    api.gitLog(20, repo).then(setLog);
  }

  useEffect(() => { refresh(); }, [repo]);

  async function handleCommit() {
    const r = await api.gitCommit(commitMsg, false, repo);
    setMsg(r.success ? `Committed: ${r.commit_hash}` : `Error: ${r.error}`);
    setCommitMsg("");
    refresh();
  }

  async function handleAutoCommit() {
    const r = await api.gitCommit("", true, repo);
    setMsg(r.success ? `Auto-committed: ${r.commit_hash}` : `Error: ${r.error}`);
    refresh();
  }

  async function handlePush() {
    const r = await api.gitPush(repo);
    setMsg(r.ok ? "Pushed" : `Push failed: ${r.output}`);
  }

  async function handlePull() {
    const r = await api.gitPull(repo);
    setMsg(r.ok ? "Pulled" : `Pull failed: ${r.output}`);
    refresh();
  }

  async function handleCreateBranch() {
    const r = await api.gitCheckout(newBranch, true, repo);
    setMsg(r.ok ? `Created and switched to ${r.branch}` : `Error: ${r.output}`);
    setNewBranch("");
    refresh();
  }

  async function handlePr() {
    const r = await api.gitCreatePr(prTitle, prBody, repo);
    setMsg(r.success ? `PR created: ${r.url}` : `Error: ${r.error}`);
  }

  async function handleReview() {
    const r = await api.gitReview("", repo);
    setReviewResult(r);
  }

  async function loadDiff() {
    const r = await api.gitDiff(false, repo);
    setDiff(r.diff);
  }

  const sevColor = (s: string) => s === "error" ? "text-red-400" : s === "warning" ? "text-yellow-400" : "text-blue-400";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Git</h1>
        <div className="flex items-center gap-2">
          <input
            className="px-3 py-1.5 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Workspace path (optional)"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
          />
          <button onClick={refresh} className="px-3 py-1.5 rounded text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Refresh
          </button>
        </div>
      </div>

      {msg && (
        <div className="px-4 py-2 rounded text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
          {msg}
          <button onClick={() => setMsg("")} className="ml-3 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>dismiss</button>
        </div>
      )}

      {/* Status bar */}
      {status && (
        <div className="grid grid-cols-4 gap-3">
          <div className="p-3 rounded border" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
            <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Branch</div>
            <div className="text-lg font-semibold">{status.branch || "-"}</div>
          </div>
          <div className="p-3 rounded border" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
            <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Changed files</div>
            <div className="text-lg font-semibold">{status.changed_files ?? 0}</div>
          </div>
          <div className="p-3 rounded border" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
            <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Is repo</div>
            <div className="text-lg font-semibold">{status.is_repo ? "Yes" : "No"}</div>
          </div>
          <div className="p-3 rounded border" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
            <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Feature branch</div>
            <div className="text-lg font-semibold">{status.is_branch ? "Yes" : "No"}</div>
          </div>
        </div>
      )}

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2">
        <button onClick={handlePull} className="px-4 py-2 rounded-lg text-sm font-medium transition"
          style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
          Pull
        </button>
        <button onClick={handlePush} className="px-4 py-2 rounded-lg text-sm font-medium transition"
          style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
          Push
        </button>
        <div className="flex items-center gap-2">
          <input
            className="px-3 py-1.5 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Commit message"
            value={commitMsg}
            onChange={(e) => setCommitMsg(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCommit()}
          />
          <button onClick={handleCommit} className="px-3 py-1.5 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Commit
          </button>
          <button onClick={handleAutoCommit} className="px-3 py-1.5 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Auto
          </button>
        </div>
        <button onClick={loadDiff} className="px-4 py-2 rounded-lg text-sm font-medium transition"
          style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
          Show Diff
        </button>
        <button onClick={handleReview} className="px-4 py-2 rounded-lg text-sm font-medium transition"
          style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
          LLM Review
        </button>
      </div>

      {/* Branch switcher */}
      {branches && (
        <div className="flex items-center gap-2">
          <span className="text-sm" style={{ color: "var(--dt-colors-text-secondary)" }}>Branch:</span>
          <select
            className="px-3 py-1.5 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            value={branches.current}
            onChange={async (e) => {
              await api.gitCheckout(e.target.value, false, repo);
              refresh();
            }}
          >
            {branches.branches.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <input
            className="px-3 py-1.5 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="New branch name"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
          />
          <button onClick={handleCreateBranch} className="px-3 py-1.5 rounded text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Create & Switch
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["status", "log", "diff", "review", "pr"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "border-b-2" : ""}`}
            style={{
              color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderColor: tab === t ? "var(--dt-colors-accent-default)" : "transparent",
            }}>
            {t === "pr" ? "Pull Request" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab: Status */}
      {tab === "status" && status && (
        <div>
          <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--dt-colors-text-secondary)" }}>Changed files</h3>
          {status.changes?.length > 0 ? (
            <pre className="p-3 rounded text-sm overflow-x-auto"
              style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-primary)" }}>
              {status.changes.join("\n")}
            </pre>
          ) : (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Working tree clean</p>
          )}
        </div>
      )}

      {/* Tab: Log */}
      {tab === "log" && (
        <table className="w-full text-sm" style={{ color: "var(--dt-colors-text-primary)" }}>
          <thead>
            <tr className="border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
              <th className="text-left py-2 pr-4 font-mono">Hash</th>
              <th className="text-left py-2 pr-4">Message</th>
              <th className="text-left py-2 pr-4">Author</th>
              <th className="text-left py-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {log.map((entry) => (
              <tr key={entry.hash} className="border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
                <td className="py-2 pr-4 font-mono text-xs">{entry.hash}</td>
                <td className="py-2 pr-4">{entry.message}</td>
                <td className="py-2 pr-4">{entry.author}</td>
                <td className="py-2">{entry.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Tab: Diff */}
      {tab === "diff" && (
        <pre className="p-3 rounded text-sm overflow-x-auto max-h-96"
          style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-primary)" }}>
          {diff || "Click 'Show Diff' to load"}
        </pre>
      )}

      {/* Tab: Review */}
      {tab === "review" && (
        <div className="space-y-4">
          {reviewResult && (
            <>
              <div className="p-3 rounded text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <strong>Summary:</strong> {reviewResult.summary}
              </div>
              {reviewResult.comments.length > 0 ? (
                reviewResult.comments.map((c, i) => (
                  <div key={i} className="p-3 rounded border text-sm"
                    style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                    <div className="flex gap-3 mb-1">
                      <span className={`font-medium ${sevColor(c.severity)}`}>{c.severity}</span>
                      <span style={{ color: "var(--dt-colors-text-tertiary)" }}>{c.file}:{c.line}</span>
                    </div>
                    <div>{c.message}</div>
                  </div>
                ))
              ) : (
                <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No comments</p>
              )}
            </>
          )}
          <button onClick={handleReview} className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Run LLM Review
          </button>
        </div>
      )}

      {/* Tab: Pull Request */}
      {tab === "pr" && (
        <div className="space-y-4 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="PR title"
            value={prTitle}
            onChange={(e) => setPrTitle(e.target.value)}
          />
          <textarea
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="PR body (optional)"
            rows={6}
            value={prBody}
            onChange={(e) => setPrBody(e.target.value)}
          />
          <button onClick={handlePr} className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Create Pull Request
          </button>
        </div>
      )}
    </div>
  );
}
