import { useCallback,useEffect, useState } from "react";

import { api } from "../api/client";
import DiffViewer from "../components/DiffViewer";
import PageHeader from "../components/PageHeader";

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

import type { DiffFile } from "../components/DiffViewer";

interface GitStatus {
  branch?: string;
  changed_files?: number;
  is_repo?: boolean;
  is_branch?: boolean;
  changes: string[];
}

interface CommitDetail {
  hash: string;
  message: string;
  author: string;
  author_email?: string;
  date: string;
  diff: string;
  files?: DiffFile[];
  total_files: number;
  total_added: number;
  total_deleted: number;
}

interface BlameLine {
  hash: string;
  author: string;
  content: string;
}

interface BlameData {
  lines: BlameLine[];
}

type Tab = "status" | "log" | "diff" | "blame" | "review" | "pr";

export default function Git() {
  const [repo, setRepo] = useState("");
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [branches, setBranches] = useState<{ branches: string[]; current: string } | null>(null);
  const [log, setLog] = useState<CommitEntry[]>([]);
  const [diff, setDiff] = useState("");
  const [diffFiles, setDiffFiles] = useState<DiffFile[]>([]);
  const [commitMsg, setCommitMsg] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [prBody, setPrBody] = useState("");
  const [reviewResult, setReviewResult] = useState<{ summary: string; comments: ReviewComment[] } | null>(null);
  const [newBranch, setNewBranch] = useState("");
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<Tab>("status");
  const [selectedCommit, setSelectedCommit] = useState<CommitDetail | null>(null);
  const [blameFile, setBlameFile] = useState("");
  const [blameData, setBlameData] = useState<BlameData | null>(null);
  const [blameLoading, setBlameLoading] = useState(false);

  const refresh = useCallback(() => {
    api.gitStatus(repo).then(setStatus).catch(e => console.error("git status:", e));
    api.gitBranches(repo).then(setBranches).catch(e => console.error("git branches:", e));
    api.gitLog(20, repo).then(setLog).catch(e => console.error("git log:", e));
  }, [repo]);

  useEffect(() => { refresh(); }, [refresh]);

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
    setDiffFiles([]);
    setSelectedCommit(null);
    setTab("diff");
  }

  async function openCommit(hash: string) {
    setSelectedCommit(null);
    const detail = await api.gitLogDetail(hash, repo);
    if (detail.error) {
      setMsg(`Error: ${detail.error}`);
      return;
    }
    setSelectedCommit(detail);
    setDiff(detail.diff);
    setDiffFiles(detail.files || []);
    setTab("diff");
  }

  async function loadBlame() {
    if (!blameFile.trim()) return;
    setBlameLoading(true);
    try {
      const r = await api.gitBlame(blameFile.trim(), repo);
      if (r.error) {
        setMsg(`Blame error: ${r.error}`);
        setBlameData(null);
      } else {
        setBlameData(r);
      }
    } catch (e) {
      console.error("blame failed:", e);
    } finally {
      setBlameLoading(false);
    }
  }

  const sevColor = (s: string) =>
    s === "error"
      ? "var(--dt-colors-status-error)"
      : s === "warning"
        ? "var(--dt-colors-status-warning)"
        : "var(--dt-colors-status-info)";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Git"
        subtitle="Repository status, history and review tools"
        actions={
          <div className="flex items-center gap-2">
            <input
              className="input-base"
              placeholder="Workspace path (optional)"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
            />
            <button onClick={refresh} className="btn-outline px-3 py-1.5">
              Refresh
            </button>
          </div>
        }
      />

      {msg && (
        <div className="px-4 py-2 rounded text-sm flex items-center gap-2 btn-tertiary">
          <span className="flex-1">{msg}</span>
          <button onClick={() => setMsg("")} className="text-xs font-medium px-2 py-0.5 rounded text-tertiary">dismiss</button>
        </div>
      )}

      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Branch" value={status.branch || "-"} />
          <StatCard label="Changed files" value={String(status.changed_files ?? 0)} />
          <StatCard label="Is repo" value={status.is_repo ? "Yes" : "No"} />
          <StatCard label="Feature branch" value={status.is_branch ? "Yes" : "No"} />
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button onClick={handlePull} className="btn-soft px-4 py-2">Pull</button>
        <button onClick={handlePush} className="btn-soft px-4 py-2">Push</button>
        <div className="flex items-center gap-2">
          <input
            className="input-base"
            placeholder="Commit message"
            value={commitMsg}
            onChange={(e) => setCommitMsg(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCommit()}
          />
          <button onClick={handleCommit} className="btn-soft px-3 py-2">Commit</button>
          <button onClick={handleAutoCommit} className="btn-soft px-3 py-2">Auto</button>
        </div>
        <button onClick={loadDiff} className="btn-soft px-4 py-2">Show Diff</button>
        <button onClick={handleReview} className="btn-soft px-4 py-2">LLM Review</button>
      </div>

      {branches && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-secondary">Branch:</span>
          <select
            className="input-base"
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
            className="input-base"
            placeholder="New branch name"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateBranch()}
          />
          <button onClick={handleCreateBranch} className="btn-soft px-3 py-1.5">
            Create & Switch
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
        {(["status", "log", "diff", "blame", "review", "pr"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "tab-active" : "tab-inactive"}`}>
            {t === "pr" ? "Pull Request" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "status" && status && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-secondary">Changed files</h3>
          {status.changes?.length > 0 ? (
            <div className="space-y-1">
              {status.changes.map((c: string, i: number) => (
                <div key={i} className="px-3 py-1.5 rounded text-sm font-mono bg-secondary text-primary">
                  {c}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-tertiary">Working tree clean</p>
          )}
        </div>
      )}

      {tab === "log" && (
        <div className="space-y-2">
          {log.length === 0 ? (
            <p className="text-sm text-tertiary">No commits yet</p>
          ) : (
            log.map((entry) => (
              <button
                key={entry.hash}
                onClick={() => openCommit(entry.hash)}
                className="commit-card w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left group"
              >
                <span className="font-mono text-xs px-2 py-0.5 rounded flex-shrink-0" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-accent-default)" }}>
                  {entry.hash}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{entry.message}</div>
                  <div className="text-xs text-tertiary">
                    {entry.author} &middot; {entry.date}
                  </div>
                </div>
                <span className="text-xs flex-shrink-0 text-tertiary">
                  {entry.date}
                </span>
              </button>
            ))
          )}
        </div>
      )}

      {tab === "diff" && (
        <div>
          {selectedCommit && (
            <div className="mb-3 p-3 rounded-xl card-bordered">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-accent-default)" }}>
                  {selectedCommit.hash}
                </span>
                <span className="text-sm font-medium">{selectedCommit.message}</span>
              </div>
              <div className="text-xs flex flex-wrap gap-3 text-tertiary">
                <span>{selectedCommit.author} &lt;{selectedCommit.author_email}&gt;</span>
                <span>{selectedCommit.date}</span>
                <span>{selectedCommit.total_files} files</span>
                {selectedCommit.total_added > 0 && <span className="text-success">+{selectedCommit.total_added}</span>}
                {selectedCommit.total_deleted > 0 && <span className="text-danger">-{selectedCommit.total_deleted}</span>}
              </div>
            </div>
          )}
          <DiffViewer diff={diff} files={diffFiles} singlePane />
        </div>
      )}

      {tab === "blame" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <input
              className="input-base flex-1 font-mono"
              placeholder="File path (e.g. src/main.ts)"
              value={blameFile}
              onChange={(e) => setBlameFile(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadBlame()}
            />
            <button onClick={loadBlame} disabled={blameLoading}
              className="btn-soft px-4 py-1.5">
              {blameLoading ? "..." : "Blame"}
            </button>
          </div>

          {blameData?.lines && (
            <div className="overflow-auto rounded-xl border" style={{ maxHeight: "70vh", borderColor: "var(--dt-colors-border-default)" }}>
              <table className="w-full text-xs font-mono border-collapse">
                <tbody>
                  {blameData.lines.map((line, i) => {
                    const shortHash = line.hash?.slice(0, 7) || "???????";
                    return (
                      <tr key={i}>
                        <td className="px-2 py-0 align-top whitespace-nowrap select-none" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                          {i + 1}
                        </td>
                        <td className="px-2 py-0 align-top whitespace-nowrap select-none" style={{ color: "var(--dt-colors-accent-default)", backgroundColor: "var(--dt-colors-bg-secondary)" }}>
                          {shortHash}
                        </td>
                        <td className="px-2 py-0 align-top whitespace-nowrap select-none text-tertiary">
                          {line.author || "unknown"}
                        </td>
                        <td className="px-2 py-0 align-top whitespace-pre text-primary">
                          {line.content || ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "review" && (
        <div className="space-y-4">
          {reviewResult && (
            <>
              <div className="p-3 rounded text-sm bg-tertiary">
                <strong>Summary:</strong> {reviewResult.summary}
              </div>
              {reviewResult.comments.length > 0 ? (
                reviewResult.comments.map((c, i) => (
                  <div key={i} className="p-3 rounded border text-sm bg-secondary border-default">
                    <div className="flex gap-3 mb-1">
                      <span className="font-medium" style={{ color: sevColor(c.severity) }}>{c.severity}</span>
                      <span className="text-tertiary">{c.file}:{c.line}</span>
                    </div>
                    <div>{c.message}</div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-tertiary">No comments</p>
              )}
            </>
          )}
          <button onClick={handleReview} className="btn-soft px-4 py-2">
            Run LLM Review
          </button>
        </div>
      )}

      {tab === "pr" && (
        <div className="space-y-4 max-w-lg">
          <input
            className="input-base"
            placeholder="PR title"
            value={prTitle}
            onChange={(e) => setPrTitle(e.target.value)}
          />
          <textarea
            className="input-base"
            placeholder="PR body (optional)"
            rows={6}
            value={prBody}
            onChange={(e) => setPrBody(e.target.value)}
          />
          <button onClick={handlePr} className="btn-soft px-4 py-2">
            Create Pull Request
          </button>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-card">
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value">{value}</div>
    </div>
  );
}
