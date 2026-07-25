import { request } from "./client";
import type {
GitHubBranch, GitHubCloneResult, GitHubComment, GitHubContentItem,   GitHubCreateResult, GitHubFileEntry,
GitHubFileTreeItem,   GitHubIssue, GitHubMergeResult,
GitHubPull, GitHubRateLimit, GitHubRepo, GitHubReview,   GitHubSearchCodeResult, GitHubSearchReposResult,
GitHubTokenStatus,   GitHubUser, GitHubWorkflowDispatch,
} from "./types";

export const githubApi = {
  githubUser: () => request<GitHubUser>("/api/github/user"),
  githubRepos: (page = 1, perPage = 30, sort = "updated") =>
    request<GitHubRepo[]>(`/api/github/repos?page=${page}&per_page=${perPage}&sort=${sort}`),
  githubRepo: (owner: string, repo: string) => request<GitHubRepo>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`),
  githubBranches: (owner: string, repo: string) => request<GitHubBranch[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`),
  githubContents: (owner: string, repo: string, path = "", ref?: string) =>
    request<GitHubContentItem[] | GitHubFileEntry>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${encodeURIComponent(path)}${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`),
  githubPulls: (owner: string, repo: string, state = "open") =>
    request<GitHubPull[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls?state=${state}`),
  githubPull: (owner: string, repo: string, number: number) =>
    request<GitHubPull>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}`),
  githubPullFiles: (owner: string, repo: string, number: number) =>
    request<{ filename: string; status: string; additions: number; deletions: number; changes: number; patch?: string }[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/files`),
  githubIssues: (owner: string, repo: string, state = "open") =>
    request<GitHubIssue[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues?state=${state}`),
  githubCreatePR: (owner: string, repo: string, title: string, body = "", head = "main", base = "main") =>
    request<GitHubCreateResult>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls`, {
      method: "POST", body: JSON.stringify({ owner, repo, title, body, head, base }),
    }),
  githubCreateIssue: (owner: string, repo: string, title: string, body = "", labels: string[] = []) =>
    request<GitHubCreateResult>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues`, {
      method: "POST", body: JSON.stringify({ owner, repo, title, body, labels }),
    }),
  githubTriggerWorkflow: (owner: string, repo: string, workflowId: string, ref = "main", inputs: Record<string, string> = {}) =>
    request<GitHubWorkflowDispatch>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/actions/workflows/${encodeURIComponent(workflowId)}/dispatches`, {
      method: "POST", body: JSON.stringify({ owner, repo, workflow_id: workflowId, ref, inputs }),
    }),
  githubSearchRepos: (q: string, page = 1, perPage = 10) =>
    request<GitHubSearchReposResult>(`/api/github/search/repos?q=${encodeURIComponent(q)}&page=${page}&per_page=${perPage}`),
  githubRateLimit: () => request<GitHubRateLimit>("/api/github/rate-limit"),
  githubFileTree: (owner: string, repo: string, ref = "main") =>
    request<GitHubFileTreeItem[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/tree?ref=${encodeURIComponent(ref)}`),
  githubCloneRepo: (owner: string, repo: string, branch = "main", targetDir = "") =>
    request<GitHubCloneResult>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/clone`, {
      method: "POST", body: JSON.stringify({ owner, repo, branch, target_dir: targetDir }),
    }),
  githubMergePR: (owner: string, repo: string, number: number, mergeMethod = "merge", commitTitle = "", commitMessage = "") =>
    request<GitHubMergeResult>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/merge`, {
      method: "POST", body: JSON.stringify({ owner, repo, pull_number: number, commit_title: commitTitle, commit_message: commitMessage, merge_method: mergeMethod }),
    }),
  githubCreateReview: (owner: string, repo: string, number: number, body = "", event = "COMMENT", commitId = "") =>
    request<GitHubReview>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/reviews`, {
      method: "POST", body: JSON.stringify({ owner, repo, pull_number: number, body, event, commit_id: commitId }),
    }),
  githubListReviews: (owner: string, repo: string, number: number) =>
    request<GitHubReview[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/reviews`),
  githubIssueComments: (owner: string, repo: string, number: number) =>
    request<GitHubComment[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments`),
  githubCreateComment: (owner: string, repo: string, number: number, body: string) =>
    request<GitHubComment>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments`, {
      method: "POST", body: JSON.stringify({ body }),
    }),
  githubSearchCode: (owner: string, repo: string, query: string, page = 1, perPage = 10) =>
    request<GitHubSearchCodeResult>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/search/code?q=${encodeURIComponent(query)}&page=${page}&per_page=${perPage}`),
  githubTokenStatus: () => request<GitHubTokenStatus>("/api/github/token/status"),
  githubSetToken: (token: string) =>
    request<{ ok: boolean }>("/api/github/token", { method: "POST", body: JSON.stringify({ token }) }),
};
