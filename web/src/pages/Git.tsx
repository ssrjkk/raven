import { useCallback,useEffect, useState } from "react";

import { api } from "../api/client";
import DiffViewer from "../components/DiffViewer";

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

  const sevColor = (s: string) => s === "error" ? "text-red-400" : s === "warning" ? "text-yellow-400" : "text-blue-400";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Git</h1>
        <div className="flex items-center gap-2">
          <input
            className="px-3 py-1.5 rounded border text-sm card-bordered text-primary"
            placeholder="Workspace path (optional)"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
          />
          <button onClick={refresh} className="px-3 py-1.5 rounded text-sm font-medium transition bg-accent-muted text-accent">
            Refresh
          </button>
        </div>
      </div>

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
        <button onClick={handlePull} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
          Pull
        </button>
        <button onClick={handlePush} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
          Push
        </button>
        <div className="flex items-center gap-2">
          <input
            className="px-3 py-1.5 rounded border text-sm card-bordered text-primary"
            placeholder="Commit message"
            value={commitMsg}
            onChange={(e) => setCommitMsg(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCommit()}
          />
          <button onClick={handleCommit} className="px-3 py-1.5 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            Commit
          </button>
          <button onClick={handleAutoCommit} className="px-3 py-1.5 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            Auto
          </button>
        </div>
        <button onClick={loadDiff} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
          Show Diff
        </button>
        <button onClick={handleReview} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
          LLM Review
        </button>
      </div>

      {branches && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-secondary">Branch:</span>
          <select
            className="px-3 py-1.5 rounded border text-sm card-bordered text-primary"
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
            className="px-3 py-1.5 rounded border text-sm card-bordered text-primary"
            placeholder="New branch name"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateBranch()}
          />
          <button onClick={handleCreateBranch} className="px-3 py-1.5 rounded text-sm font-medium transition bg-accent-muted text-accent">
            Create & Switch
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
        {(["status", "log", "diff", "blame", "review", "pr"] as const).map((t) => (
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
                className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left transition hover:opacity-80"
                style={{
                  backgroundColor: "var(--dt-colors-bg-secondary)",
                  border: "1px solid var(--dt-colors-border-default)",
                  color: "var(--dt-colors-text-primary)",
                }}
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
                {selectedCommit.total_added > 0 && <span className="text-green-500">+{selectedCommit.total_added}</span>}
                {selectedCommit.total_deleted > 0 && <span className="text-red-500">-{selectedCommit.total_deleted}</span>}
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
              className="flex-1 px-3 py-1.5 rounded border text-sm font-mono card-bordered text-primary"
              placeholder="File path (e.g. src/main.ts)"
              value={blameFile}
              onChange={(e) => setBlameFile(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadBlame()}
            />
            <button onClick={loadBlame} disabled={blameLoading}
              className="px-4 py-1.5 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
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
                      <span className={`font-medium ${sevColor(c.severity)}`}>{c.severity}</span>
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
          <button onClick={handleReview} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            Run LLM Review
          </button>
        </div>
      )}

      {tab === "pr" && (
        <div className="space-y-4 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm card-bordered text-primary"
            placeholder="PR title"
            value={prTitle}
            onChange={(e) => setPrTitle(e.target.value)}
          />
          <textarea
            className="w-full px-3 py-2 rounded border text-sm card-bordered text-primary"
            placeholder="PR body (optional)"
            rows={6}
            value={prBody}
            onChange={(e) => setPrBody(e.target.value)}
          />
          <button onClick={handlePr} className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            Create Pull Request
          </button>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 rounded-xl border bg-secondary border-default">
      <div className="text-xs text-tertiary">{label}</div>
      <div className="text-lg font-semibold text-primary">{value}</div>
    </div>
  );
}
