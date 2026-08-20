import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

interface Repo {
  id: number;
  full_name: string;
  name: string;
  owner: { login: string; avatar_url: string };
  description: string;
  language: string;
  stargazers_count: number;
  forks_count: number;
  html_url: string;
  default_branch: string;
  updated_at: string;
}

interface Branch {
  name: string;
  commit: { sha: string };
}

interface PullRequest {
  number: number;
  title: string;
  state: string;
  user: { login: string };
  created_at: string;
  head: { ref: string; sha: string };
  base: { ref: string };
  body: string | null;
  html_url: string;
  mergeable: boolean | null;
}

interface FileItem {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
  sha: string;
}

interface Issue {
  number: number;
  title: string;
  state: string;
  user: { login: string };
  created_at: string;
  labels: { name: string; color: string }[];
}

interface GitHubUser {
  login: string;
  avatar_url: string;
  public_repos: number;
}

interface TokenStatus {
  configured: boolean;
}

interface CodeSearchResult {
  path: string;
  name: string;
}

export default function GitHub() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [currentBranch, setCurrentBranch] = useState("main");
  const [contents, setContents] = useState<FileItem[]>([]);
  const [contentPath, setContentPath] = useState("");
  const [pulls, setPulls] = useState<PullRequest[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [tab, setTab] = useState<"files" | "pulls" | "issues" | "new-pr" | "new-issue" | "search">("files");
  const [searchQuery, setSearchQuery] = useState("");
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [msg, setMsg] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [prBody, setPrBody] = useState("");
  const [prHead, setPrHead] = useState("");
  const [prBase, setPrBase] = useState("");
  const [issueTitle, setIssueTitle] = useState("");
  const [issueBody, setIssueBody] = useState("");
  const [issueLabels, setIssueLabels] = useState("");
  const [newToken, setNewToken] = useState("");
  const [tokenStatus, setTokenStatus] = useState<TokenStatus | null>(null);
  const [fileViewer, setFileViewer] = useState<{ path: string; content: string } | null>(null);
  const [codeQuery, setCodeQuery] = useState("");
  const [codeResults, setCodeResults] = useState<CodeSearchResult[]>([]);
  const [cloning, setCloning] = useState(false);
  const repoSeqRef = useRef(0);

  useEffect(() => {
    api.githubTokenStatus().then(setTokenStatus).catch(() => setTokenStatus(null));
    api.githubUser().then(setUser).catch(() => setUser(null));
    loadRepos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadRepos() {
    try {
      const data = await api.githubRepos();
      setRepos(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); setRepos([]); }
  }

  async function searchRepos() {
    if (!searchQuery.trim()) { loadRepos(); return; }
    try {
      const data = await api.githubSearchRepos(searchQuery);
      setRepos(data?.items ?? []);
    } catch (e) { console.error(e); setRepos([]); }
  }

  async function selectRepo(fullName: string) {
    setSelectedRepo(fullName);
    setTab("files");
    setContentPath("");
    setFileViewer(null);
    const seq = ++repoSeqRef.current;
    const [owner, repo] = fullName.split("/");
    try {
      const b = await api.githubBranches(owner, repo);
      if (seq !== repoSeqRef.current) return;
      setBranches(Array.isArray(b) ? b : []);
      const def = (Array.isArray(b) && b.length > 0) ? b[0].name : "main";
      setCurrentBranch(def);
      loadContents(owner, repo, "", def);
      const p = await api.githubPulls(owner, repo);
      if (seq === repoSeqRef.current) setPulls(Array.isArray(p) ? p : []);
      const iss = await api.githubIssues(owner, repo);
      if (seq === repoSeqRef.current) setIssues(Array.isArray(iss) ? iss : []);
    } catch (e) { if (seq === repoSeqRef.current) { console.error(e); setBranches([]); setPulls([]); setIssues([]); } }
  }

  async function loadContents(owner: string, repo: string, path: string, ref: string) {
    const seq = repoSeqRef.current;
    try {
      const data = await api.githubContents(owner, repo, path, ref);
      if (seq !== repoSeqRef.current) return;
      setContents(Array.isArray(data) ? data : []);
      setContentPath(path);
      setFileViewer(null);
    } catch (e) { if (seq === repoSeqRef.current) { console.error(e); setContents([]); } }
  }

  function navigateDir(dir: string) {
    if (!selectedRepo) return;
    const [owner, repo] = selectedRepo.split("/");
    const newPath = contentPath ? `${contentPath}/${dir}` : dir;
    loadContents(owner, repo, newPath, currentBranch);
  }

  function goUp() {
    if (!selectedRepo || !contentPath) return;
    const [owner, repo] = selectedRepo.split("/");
    const parent = contentPath.split("/").slice(0, -1).join("/");
    loadContents(owner, repo, parent, currentBranch);
  }

  async function openFile(path: string) {
    if (!selectedRepo) return;
    const [owner, repo] = selectedRepo.split("/");
    try {
      const data = await api.githubContents(owner, repo, path, currentBranch);
      if (!Array.isArray(data) && data.content) {
        const decoded = atob(data.content.replace(/\n/g, ""));
        setFileViewer({ path, content: decoded });
      }
    } catch (e) { console.error(e); setMsg(`Failed to open ${path}`); }
  }

  function closeFileViewer() {
    setFileViewer(null);
  }

  async function switchBranch(branch: string) {
    setCurrentBranch(branch);
    if (!selectedRepo) return;
    const [owner, repo] = selectedRepo.split("/");
    loadContents(owner, repo, contentPath, branch);
  }

  async function createPR() {
    if (!selectedRepo || !prTitle.trim()) return;
    const [owner, repo] = selectedRepo.split("/");
    try {
      const r = await api.githubCreatePR(owner, repo, prTitle, prBody, prHead || currentBranch, prBase || "main");
      setMsg(`PR #${r.number} created: ${r.html_url}`);
      setPrTitle(""); setPrBody(""); setPrHead(""); setPrBase("");
      const p = await api.githubPulls(owner, repo);
      setPulls(Array.isArray(p) ? p : []);
    } catch (e) { setMsg(`Error: ${e}`); }
  }

  async function mergePR(number: number) {
    if (!selectedRepo) return;
    const [owner, repo] = selectedRepo.split("/");
    try {
      const r = await api.githubMergePR(owner, repo, number);
      setMsg(`PR #${number} merged: ${r.sha ? r.sha.slice(0, 7) : "done"}`);
      const p = await api.githubPulls(owner, repo);
      setPulls(Array.isArray(p) ? p : []);
    } catch (e) { setMsg(`Merge failed: ${e}`); }
  }

  async function cloneRepo() {
    if (!selectedRepo) return;
    const [owner, repo] = selectedRepo.split("/");
    setCloning(true);
    try {
      const r = await api.githubCloneRepo(owner, repo, currentBranch);
      setMsg(`Cloned to ${r.path}`);
    } catch (e) { setMsg(`Clone failed: ${e}`); }
    setCloning(false);
  }

  async function createIssue() {
    if (!selectedRepo || !issueTitle.trim()) return;
    const [owner, repo] = selectedRepo.split("/");
    try {
      const labels = issueLabels.split(",").map((s) => s.trim()).filter(Boolean);
      const r = await api.githubCreateIssue(owner, repo, issueTitle, issueBody, labels);
      setMsg(`Issue #${r.number} created`);
      setIssueTitle(""); setIssueBody(""); setIssueLabels("");
      const iss = await api.githubIssues(owner, repo);
      setIssues(Array.isArray(iss) ? iss : []);
    } catch (e) { setMsg(`Error: ${e}`); }
  }

  async function setToken() {
    if (!newToken.trim()) return;
    try {
      await api.githubSetToken(newToken.trim());
      setMsg("GitHub token saved");
      setNewToken("");
      const status = await api.githubTokenStatus();
      setTokenStatus(status);
      const u = await api.githubUser();
      setUser(u);
    } catch (e) { setMsg(`Token error: ${e}`); }
  }

  async function searchCode() {
    if (!selectedRepo || !codeQuery.trim()) return;
    const [owner, repo] = selectedRepo.split("/");
    try {
      const data = await api.githubSearchCode(owner, repo, codeQuery);
      setCodeResults(data?.items ?? []);
    } catch (e) { setMsg(`Code search error: ${e}`); setCodeResults([]); }
  }


  if (!tokenStatus?.configured) {
    return (
      <div className="space-y-6">
        <PageHeader title="GitHub" subtitle="Connect your GitHub account" />
        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Configure GitHub Token</h2>
          <p className="text-sm mb-4 text-tertiary">
            Enter a GitHub personal access token with <code>repo</code> scope to browse repositories, create PRs, and more.
          </p>
          <div className="flex gap-2">
            <input
              className="input-base flex-1 font-mono"
              placeholder="ghp_..."
              value={newToken}
              onChange={(e) => setNewToken(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setToken()}
            />
            <button onClick={setToken} className="btn-primary shrink-0">
              Save Token
            </button>
          </div>
          {msg && <p className="text-xs mt-2">{msg}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="GitHub" subtitle="Browse repositories, pull requests, and issues" />

      {msg && (
        <div className="px-4 py-2 rounded text-sm flex items-center justify-between btn-tertiary">
          <span>{msg}</span>
          <button onClick={() => setMsg("")} className="text-xs text-tertiary">dismiss</button>
        </div>
      )}

      {user && (
        <div className="flex items-center gap-3 text-sm p-3 rounded-lg bg-secondary">
          <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full" />
          <span className="font-medium">{user.login}</span>
          <span className="text-tertiary">{user.public_repos} public repos</span>
        </div>
      )}

      <div className="flex gap-2">
        <input
          className="input-base flex-1"
          placeholder={user ? "Search your repos..." : "Loading..."}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && searchRepos()}
          disabled={!user}
        />
        <button onClick={searchRepos} className="btn-primary shrink-0">
          Search
        </button>
      </div>

      <div className="flex gap-6">
        <div className="w-64 flex-shrink-0 space-y-1 max-h-[70vh] overflow-y-auto">
          {repos.map((r) => (
            <button
              key={r.id}
              onClick={() => selectRepo(r.full_name)}
              className="w-full text-left p-2 rounded text-xs transition border"
              style={{
                backgroundColor: selectedRepo === r.full_name ? "var(--dt-colors-accent-muted)" : "var(--dt-colors-bg-secondary)",
                borderColor: selectedRepo === r.full_name ? "var(--dt-colors-accent-subtle)" : "transparent",
                color: "var(--dt-colors-text-primary)",
              }}
            >
              <div className="font-medium text-sm truncate">{r.full_name}</div>
              {r.description && <div className="truncate mt-0.5 text-tertiary">{r.description}</div>}
              <div className="flex gap-2 mt-1">
                {r.language && <span className="chip">{r.language}</span>}
                <span className="text-[10px] text-tertiary">S {r.stargazers_count}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="flex-1 min-w-0">
          {!selectedRepo ? (
            <div className="text-sm py-8 text-center text-tertiary">
              Select a repository to browse
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold truncate">{selectedRepo}</h2>
                <div className="flex items-center gap-2">
                  <button onClick={cloneRepo} disabled={cloning} className="btn-primary">
                    {cloning ? "Cloning..." : "Clone"}
                  </button>
                  <select
                    className="input-base text-xs! w-auto!"
                    value={currentBranch}
                    onChange={(e) => switchBranch(e.target.value)}
                  >
                    {branches.map((b) => (
                      <option key={b.name} value={b.name}>{b.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex gap-1 mb-3 border-b pb-1 border-default">
                {(["files", "pulls", "issues", "new-pr", "new-issue", "search"] as const).map((t) => (
                  <button key={t} onClick={() => setTab(t)}
                    className="px-3 py-1 text-xs rounded-t transition"
                    style={{
                      backgroundColor: tab === t ? "var(--dt-colors-accent-muted)" : "transparent",
                      color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
                    }}>
                    {t === "files" ? "Files" : t === "pulls" ? `PRs (${pulls.length})` : t === "issues" ? `Issues (${issues.length})` : t === "new-pr" ? "New PR" : t === "new-issue" ? "New Issue" : "Code"}
                  </button>
                ))}
              </div>

              {tab === "files" && (
                <div className="space-y-0.5">
                  {fileViewer ? (
                    <div>
                      <button onClick={closeFileViewer} className="btn-ghost mb-2 text-xs!">
                        &larr; Back to files
                      </button>
                      <div className="card p-3">
                        <div className="text-xs font-mono mb-2 text-tertiary">{fileViewer.path}</div>
                        <pre className="text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-[60vh] overflow-y-auto text-primary">{fileViewer.content}</pre>
                      </div>
                    </div>
                  ) : (
                    <>
                      {contentPath && (
                        <button onClick={goUp}
                          className="w-full text-left p-2 rounded text-sm transition"
                          style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-secondary)" }}>
                          ../
                        </button>
                      )}
                      {contents.map((item) => (
                        <div
                          key={item.path}
                          onClick={() => item.type === "dir" ? navigateDir(item.name) : openFile(item.path)}
                          className="flex items-center gap-2 p-2 rounded text-sm cursor-pointer transition bg-secondary text-primary"
                        >
                          <span>{item.type === "dir" ? "D" : "F"}</span>
                          <span className="flex-1">{item.name}</span>
                          {item.type === "file" && (
                            <span className="text-[10px] text-tertiary">{(item.size / 1024).toFixed(1)} KB</span>
                          )}
                        </div>
                      ))}
                      {contents.length === 0 && (
                        <p className="text-xs py-4 text-center text-tertiary">Empty directory</p>
                      )}
                    </>
                  )}
                </div>
              )}

              {tab === "pulls" && (
                <div className="space-y-2">
                  {pulls.length === 0 && <p className="text-xs py-4 text-center text-tertiary">No pull requests</p>}
                  {pulls.map((pr) => (
                    <div key={pr.number} className="card p-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium text-sm" style={{ color: "var(--dt-colors-accent-default)" }}>
                            #{pr.number} {pr.title}
                          </div>
                          <div className="text-xs mt-0.5 text-tertiary">
                            {pr.user.login} &mdash; {pr.head.ref} &rarr; {pr.base.ref}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="badge" style={
                            pr.state === "open"
                              ? { color: "var(--dt-colors-status-success)", backgroundColor: "var(--dt-colors-status-success-bg)" }
                              : { color: "var(--dt-colors-text-secondary)", backgroundColor: "var(--dt-colors-bg-tertiary)" }
                          }>
                            {pr.state}
                          </span>
                          {pr.state === "open" && (
                            <button onClick={() => mergePR(pr.number)} className="btn-primary text-xs! px-3! py-1!">
                              Merge
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {tab === "issues" && (
                <div className="space-y-2">
                  {issues.length === 0 && <p className="text-xs py-4 text-center text-tertiary">No issues</p>}
                  {issues.map((iss) => (
                    <div key={iss.number} className="card p-3">
                      <div className="flex items-center gap-2">
                        <span className={iss.state === "open" ? "badge badge-success" : "badge"}>{iss.state === "open" ? "O" : "C"}</span>
                        <div className="flex-1">
                          <span className="font-medium text-sm">#{iss.number} {iss.title}</span>
                          <div className="text-xs text-tertiary">{iss.user.login}</div>
                        </div>
                        <div className="flex gap-1">
                          {iss.labels?.map((l) => (
                            <span key={l.name} className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: `#${l.color}22`, color: `#${l.color}` }}>
                              {l.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {tab === "new-pr" && (
                <div className="card p-4 space-y-3">
                  <h3 className="text-sm font-semibold">New Pull Request</h3>
                  <input
                    className="input-base"
                    placeholder="Title"
                    value={prTitle}
                    onChange={(e) => setPrTitle(e.target.value)}
                  />
                  <textarea
                    className="input-base"
                    placeholder="Description (supports Markdown)"
                    rows={4}
                    value={prBody}
                    onChange={(e) => setPrBody(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <input
                      className="input-base flex-1"
                      placeholder={`Head branch (default: ${currentBranch})`}
                      value={prHead}
                      onChange={(e) => setPrHead(e.target.value)}
                    />
                    <span className="self-center text-xs text-tertiary">&rarr;</span>
                    <input
                      className="input-base flex-1"
                      placeholder="Base branch (default: main)"
                      value={prBase}
                      onChange={(e) => setPrBase(e.target.value)}
                    />
                  </div>
                  <button onClick={createPR} className="btn-primary">
                    Create Pull Request
                  </button>
                </div>
              )}

              {tab === "new-issue" && (
                <div className="card p-4 space-y-3">
                  <h3 className="text-sm font-semibold">New Issue</h3>
                  <input
                    className="input-base"
                    placeholder="Title"
                    value={issueTitle}
                    onChange={(e) => setIssueTitle(e.target.value)}
                  />
                  <textarea
                    className="input-base"
                    placeholder="Description (supports Markdown)"
                    rows={4}
                    value={issueBody}
                    onChange={(e) => setIssueBody(e.target.value)}
                  />
                  <input
                    className="input-base"
                    placeholder="Labels (comma separated: bug, enhancement, documentation)"
                    value={issueLabels}
                    onChange={(e) => setIssueLabels(e.target.value)}
                  />
                  <button onClick={createIssue} className="btn-primary">
                    Create Issue
                  </button>
                </div>
              )}

              {tab === "search" && (
                <div className="space-y-3">
                  <div className="flex gap-2">
                    <input
                      className="input-base flex-1 font-mono"
                      placeholder="Search code in repository..."
                      value={codeQuery}
                      onChange={(e) => setCodeQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && searchCode()}
                    />
                    <button onClick={searchCode} className="btn-primary shrink-0">
                      Search
                    </button>
                  </div>
                  {codeResults.length > 0 && (
                    <div className="space-y-1">
                      {codeResults.map((item, i) => (
                        <div key={i} className="p-2 rounded text-xs bg-secondary text-primary">
                          <span style={{ color: "var(--dt-colors-accent-default)" }}>{item.path}</span>
                          <span className="ml-2 text-tertiary">{item.name}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {codeResults.length === 0 && codeQuery && (
                    <p className="text-xs py-4 text-center text-tertiary">No results</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
