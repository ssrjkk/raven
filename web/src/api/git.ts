import { request } from "./client";
import type {
DiffFileInfo, GitBlameResult,
GitBranchInfo, GitCommitDetail, GitCommitEntry,   GitStatusData, } from "./types";

export const gitApi = {
  gitStatus: (repo?: string) => request<GitStatusData>(`/api/git/status${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitBranch: (repo?: string) => request<GitBranchInfo>(`/api/git/branch${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitBranches: (repo?: string) => request<{ branches: string[]; current: string }>(`/api/git/branches${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitLog: (count = 10, repo?: string) => request<GitCommitEntry[]>(`/api/git/log?count=${count}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  gitLogDetail: (commitHash: string, repo?: string) =>
    request<GitCommitDetail>(`/api/git/log/detail/${commitHash}${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitDiff: (staged = false, repo?: string) => request<{ diff: string }>(`/api/git/diff?staged=${staged}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  gitDiffCommit: (commitHash: string, repo?: string) =>
    request<{ diff: string; files: DiffFileInfo[] }>(`/api/git/diff/commit/${commitHash}${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitBlame: (file: string, repo?: string) =>
    request<GitBlameResult>(`/api/git/blame?file=${encodeURIComponent(file)}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  gitCommit: (message: string, auto = false, repo?: string) =>
    request<{ success: boolean; message: string; commit_hash: string; error: string }>("/api/git/commit", {
      method: "POST", body: JSON.stringify({ message, auto, repo }),
    }),
  gitPush: (repo?: string) => request<{ ok: boolean; output: string }>("/api/git/push", { method: "POST", body: JSON.stringify({ repo }) }),
  gitPull: (repo?: string) => request<{ ok: boolean; output: string }>("/api/git/pull", { method: "POST", body: JSON.stringify({ repo }) }),
  gitCheckout: (branch: string, create = false, repo?: string) =>
    request<{ ok: boolean; output: string; branch: string }>("/api/git/checkout", {
      method: "POST", body: JSON.stringify({ branch, create, repo }),
    }),
  gitCreatePr: (title: string, body = "", repo?: string) =>
    request<{ success: boolean; url: string; error: string }>("/api/git/pr", {
      method: "POST", body: JSON.stringify({ title, body, repo }),
    }),
  gitReview: (filePath = "", repo?: string) =>
    request<{ summary: string; comments: { file: string; line: number; severity: string; message: string }[] }>(
      "/api/git/review",
      { method: "POST", body: JSON.stringify({ file_path: filePath, repo }) },
    ),
};
