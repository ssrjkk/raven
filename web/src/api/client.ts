export interface Session {
  id: string;
  channel: string;
  user_id: string;
  agent_id: string;
  updated_at: string;
}

export interface MessageData {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
}

export interface StatusData {
  status: string;
  channels: string[];
  plugins: number;
  agents: { id: string; system_prompt: string; model: string | null }[];
  model: string;
}

export interface ChannelInfo {
  id: string;
  type: string;
  ready: boolean;
  stats: Record<string, number>;
}

export interface HealthCheck {
  name: string;
  ok: boolean;
  latency_ms: number;
  critical: boolean;
}

export interface HealthData {
  overall: boolean;
  checks: HealthCheck[];
}

export interface MetricsSnapshot {
  [key: string]: number;
}

export interface MonitorData {
  id: string;
  name: string;
  type: string;
  target: string;
  interval_seconds: number;
  status: string;
  last_check: { status: string; checked_at: number } | null;
}

export interface RoutineData {
  id: string;
  name: string;
  action: string;
  schedule: string;
  trigger: string;
  status: string;
  last_run_status: string | null;
}

export interface TaskData {
  id: string;
  goal: string;
  status: string;
  steps: { order: number; description: string; tool: string; status: string }[];
  created_at: number;
}

export interface CodingSessionData {
  id: string;
  goal: string;
  status: string;
  project_path: string;
  files: number;
}

export interface WsMessage {
  type: "message";
  role: string;
  content: string;
  session_id: string;
}

export interface AuthData {
  token: string;
  user: { id: string; role: string };
}

const BASE = "";

let _token: string | null = null;

export function getToken(): string | null {
  return _token;
}

export function setToken(token: string) {
  _token = token;
}

export function clearToken() {
  _token = null;
}

export function isAuthenticated(): boolean {
  return !!_token;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers,
      signal: controller.signal,
      ...init,
    });
    if (res.status === 401) {
      clearToken();
      window.location.href = "/login";
      throw new Error("Unauthorized");
    }
    if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  status: () => request<StatusData>("/api/status"),
  sessions: () => request<Session[]>("/api/sessions"),
  sessionMessages: (id: string) => request<MessageData[]>(`/api/messages/${id}`),
  createSession: () => request<{ id: string; channel: string }>("/api/sessions", { method: "POST" }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
  agents: () => request<StatusData["agents"]>("/api/agents"),
  health: () => request<HealthData>("/api/health"),
  metrics: () => request<MetricsSnapshot>("/api/metrics"),
  channels: () => request<ChannelInfo[]>("/api/admin/channels"),
  systemStatus: () => request<{ channels: number; agents: number; running: boolean; version: string }>("/api/admin/system/status"),
  monitors: (limit = 50, offset = 0) => request<MonitorData[]>(`/api/monitor/list?limit=${limit}&offset=${offset}`),
  monitorToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/monitor/${action}/${id}`, { method: "POST" }),
  routines: (limit = 50, offset = 0) => request<RoutineData[]>(`/api/routine/list?limit=${limit}&offset=${offset}`),
  routineToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/routine/${action}/${id}`, { method: "POST" }),
  tasks: (limit = 50, offset = 0) => request<TaskData[]>(`/api/task/list?limit=${limit}&offset=${offset}`),
  taskRun: (goal: string) => request<{ id: string }>("/api/task/run", { method: "POST", body: JSON.stringify({ goal }) }),
  taskCancel: (id: string) => request<{ ok: boolean }>(`/api/task/${id}/cancel`, { method: "POST" }),
  codeSessions: (limit = 20, offset = 0) => request<CodingSessionData[]>(`/api/code/list?limit=${limit}&offset=${offset}`),
  config: () => request<Record<string, string>>("/api/admin/config"),
  shutdown: () => request<{ ok: boolean }>("/api/shutdown", { method: "POST" }),
  login: (username: string, password: string) =>
    request<AuthData>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<AuthData>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
  routineCreate: (data: any) => request<{ ok: boolean; id: string }>("/api/routine/create", { method: "POST", body: JSON.stringify(data) }),
  routineDelete: (id: string) => request<{ ok: boolean }>(`/api/routine/${id}`, { method: "DELETE" }),
  workflowInstantiate: (templateId: string, config?: any) =>
    request<{ ok: boolean; task_id: string }>(`/api/admin/workflows/${templateId}/instantiate`, { method: "POST", body: JSON.stringify({ config: config || {} }) }),
  workflowSchedule: (templateId: string, config?: any) =>
    request<{ ok: boolean; routine_id: string }>(`/api/admin/workflows/${templateId}/schedule`, { method: "POST", body: JSON.stringify({ config: config || {} }) }),

  // ── Plugins ──────────────────────────────────────────
  plugins: () => request<any[]>("/api/plugins"),
  pluginsCatalog: (category?: string) =>
    request<any[]>(`/api/plugins/catalog${category ? `?category=${encodeURIComponent(category)}` : ""}`),
  pluginsSearch: (q: string) => request<any[]>(`/api/plugins/search?q=${encodeURIComponent(q)}`),
  pluginsInstall: (url: string) =>
    request<{ ok?: boolean; error?: string; name?: string; version?: string }>("/api/plugins/install", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  pluginsUninstall: (name: string) =>
    request<{ ok?: boolean; error?: string }>(`/api/plugins/uninstall/${encodeURIComponent(name)}`, { method: "POST" }),
  pluginsUpdate: (name: string) =>
    request<{ ok?: boolean; error?: string }>(`/api/plugins/update/${encodeURIComponent(name)}`, { method: "POST" }),
  pluginsTop: (limit = 10) => request<any[]>(`/api/plugins/top?limit=${limit}`),

  // ── OAuth / SSO ──────────────────────────────────────
  oauthProviders: () => request<{ providers: { name: string; icon: string; enabled: boolean }[] }>("/api/admin/auth/oauth/providers"),
  oauthAuthorize: (provider: string, redirectUri = "") =>
    request<{ url: string }>(`/api/admin/auth/oauth/authorize/${provider}?redirect_uri=${encodeURIComponent(redirectUri)}`),
  oauthCallback: (provider: string, code: string, state: string) =>
    request<any>(`/api/admin/auth/oauth/callback/${provider}`, { method: "POST", body: JSON.stringify({ code, state }) }),

  // ── Cost Management ──────────────────────────────────
  costUsage: (model: string, inputTokens: number, outputTokens: number, userId = "", channel = "", sessionId = "") =>
    request<any>("/api/cost/usage", {
      method: "POST", body: JSON.stringify({ model, input_tokens: inputTokens, output_tokens: outputTokens, user_id: userId, channel, session_id: sessionId }),
    }),
  costSummary: (hours = 24) => request<any>(`/api/cost/summary?hours=${hours}`),
  costPricing: () => request<{ pricing: Record<string, any> }>("/api/cost/pricing"),
  costSetPricing: (model: string, inputPer1k: number, outputPer1k: number) =>
    request<any>(`/api/cost/pricing/${encodeURIComponent(model)}`, {
      method: "PUT", body: JSON.stringify({ input_per_1k: inputPer1k, output_per_1k: outputPer1k }),
    }),
  costCreateBudget: (name: string, dailyLimit: number, monthlyLimit: number) =>
    request<any>("/api/cost/budgets", { method: "POST", body: JSON.stringify({ name, daily_limit: dailyLimit, monthly_limit: monthlyLimit }) }),
  costBudgets: () => request<{ budgets: any[] }>("/api/cost/budgets"),
  costDeleteBudget: (id: string) => request<any>(`/api/cost/budgets/${id}`, { method: "DELETE" }),
  costCheck: () => request<any>("/api/cost/check"),

  // ── A/B Testing ──────────────────────────────────────
  abCreate: (name: string, description: string, variantsJson: string, metricName = "conversion") =>
    request<any>("/api/ab/experiments", {
      method: "POST", body: JSON.stringify({ name, description, variants_json: variantsJson, metric_name: metricName }),
    }),
  abExperiments: () => request<{ experiments: any[] }>("/api/ab/experiments"),
  abGet: (id: string) => request<any>(`/api/ab/experiments/${id}`),
  abStatus: (id: string, status: string) =>
    request<any>(`/api/ab/experiments/${id}/status`, {
      method: "POST", body: JSON.stringify({ status }),
    }),
  abDelete: (id: string) => request<{ ok: boolean }>(`/api/ab/experiments/${id}`, { method: "DELETE" }),
  abResults: (id: string) => request<any>(`/api/ab/experiments/${id}/results`),
  abAssign: (id: string, userId = "") =>
    request<{ variant: string }>(`/api/ab/experiments/${id}/assign`, {
      method: "POST", body: JSON.stringify({ user_id: userId }),
    }),
  abRecord: (id: string, variant: string, metricName = "conversion", value = 1.0, userId = "") =>
    request<{ ok: boolean }>(`/api/ab/experiments/${id}/record`, {
      method: "POST", body: JSON.stringify({ variant, metric_name: metricName, value, user_id: userId }),
    }),

  // ── Analytics ────────────────────────────────────────
  analyticsOverview: () => request<{ last_hour: any; last_24h: any }>("/api/analytics/overview"),
  analyticsMetrics: () => request<{ metrics: string[] }>("/api/analytics/metrics"),
  analyticsSeries: (metricName: string, since?: number, bucket = "5m") =>
    request<{ metric: string; data: any[] }>(`/api/analytics/series/${encodeURIComponent(metricName)}?bucket=${bucket}${since ? `&since=${since}` : ""}`),
  analyticsSummary: (since?: number) =>
    request<any>(`/api/analytics/summary${since ? `?since=${since}` : ""}`),
  analyticsAggregated: (since?: number) =>
    request<any>(`/api/analytics/aggregated${since ? `?since=${since}` : ""}`),
  analyticsToolUsage: (since?: number) =>
    request<{ tools: any[] }>(`/api/analytics/tools/usage${since ? `?since=${since}` : ""}`),
  analyticsToolBreakdown: (since?: number) =>
    request<any>(`/api/analytics/tools/breakdown${since ? `?since=${since}` : ""}`),
  analyticsFull: () => request<any>("/api/analytics/full"),

  // ── GitHub ──────────────────────────────────────────
  githubUser: () => request<any>("/api/github/user"),
  githubRepos: (page = 1, perPage = 30, sort = "updated") =>
    request<any[]>(`/api/github/repos?page=${page}&per_page=${perPage}&sort=${sort}`),
  githubRepo: (owner: string, repo: string) => request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`),
  githubBranches: (owner: string, repo: string) => request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`),
  githubContents: (owner: string, repo: string, path = "", ref?: string) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${encodeURIComponent(path)}${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`),
  githubPulls: (owner: string, repo: string, state = "open") =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls?state=${state}`),
  githubPull: (owner: string, repo: string, number: number) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}`),
  githubPullFiles: (owner: string, repo: string, number: number) =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/files`),
  githubIssues: (owner: string, repo: string, state = "open") =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues?state=${state}`),
  githubCreatePR: (owner: string, repo: string, title: string, body = "", head = "main", base = "main") =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls`, {
      method: "POST", body: JSON.stringify({ owner, repo, title, body, head, base }),
    }),
  githubCreateIssue: (owner: string, repo: string, title: string, body = "", labels: string[] = []) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues`, {
      method: "POST", body: JSON.stringify({ owner, repo, title, body, labels }),
    }),
  githubTriggerWorkflow: (owner: string, repo: string, workflowId: string, ref = "main", inputs: Record<string, string> = {}) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/actions/workflows/${encodeURIComponent(workflowId)}/dispatches`, {
      method: "POST", body: JSON.stringify({ owner, repo, workflow_id: workflowId, ref, inputs }),
    }),
  githubSearchRepos: (q: string, page = 1, perPage = 10) =>
    request<any>(`/api/github/search/repos?q=${encodeURIComponent(q)}&page=${page}&per_page=${perPage}`),
  githubRateLimit: () => request<any>("/api/github/rate-limit"),
  githubFileTree: (owner: string, repo: string, ref = "main") =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/tree?ref=${encodeURIComponent(ref)}`),
  githubCloneRepo: (owner: string, repo: string, branch = "main", targetDir = "") =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/clone`, {
      method: "POST", body: JSON.stringify({ owner, repo, branch, target_dir: targetDir }),
    }),
  githubMergePR: (owner: string, repo: string, number: number, mergeMethod = "merge", commitTitle = "", commitMessage = "") =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/merge`, {
      method: "POST", body: JSON.stringify({ owner, repo, pull_number: number, commit_title: commitTitle, commit_message: commitMessage, merge_method: mergeMethod }),
    }),
  githubCreateReview: (owner: string, repo: string, number: number, body = "", event = "COMMENT", commitId = "") =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/reviews`, {
      method: "POST", body: JSON.stringify({ owner, repo, pull_number: number, body, event, commit_id: commitId }),
    }),
  githubListReviews: (owner: string, repo: string, number: number) =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/reviews`),
  githubIssueComments: (owner: string, repo: string, number: number) =>
    request<any[]>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments`),
  githubCreateComment: (owner: string, repo: string, number: number, body: string) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments`, {
      method: "POST", body: JSON.stringify({ body }),
    }),
  githubSearchCode: (owner: string, repo: string, query: string, page = 1, perPage = 10) =>
    request<any>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/search/code?q=${encodeURIComponent(query)}&page=${page}&per_page=${perPage}`),
  githubTokenStatus: () => request<any>("/api/github/token/status"),
  githubSetToken: (token: string) =>
    request<any>("/api/github/token", { method: "POST", body: JSON.stringify({ token }) }),

  // ── Tests ────────────────────────────────────────────
  testsRun: (path?: string, marker?: string, timeout = 120, extraArgs = "") =>
    request<{ text: string }>("/api/tests/run", {
      method: "POST",
      body: JSON.stringify({ path, marker, timeout, extra_args: extraArgs }),
    }),
  testsCoverage: (path?: string, timeout = 180) =>
    request<{ text: string }>("/api/tests/coverage", {
      method: "POST",
      body: JSON.stringify({ path, timeout }),
    }),
  testsGenerate: (filePath: string) =>
    request<{ text: string }>("/api/tests/generate", {
      method: "POST",
      body: JSON.stringify({ file_path: filePath }),
    }),

  // ── CI/CD ────────────────────────────────────────────
  cicdWorkflows: (owner?: string, repo?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/workflows?owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&provider=${provider}`),
  cicdRun: (workflowId: string, owner?: string, repo?: string, ref = "main", inputs = "", provider = "github") =>
    request<{ text: string }>("/api/cicd/run", {
      method: "POST",
      body: JSON.stringify({ workflow_id: workflowId, owner, repo, ref, inputs, provider }),
    }),
  cicdStatus: (pipelineId: string, owner?: string, repo?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/status?pipeline_id=${encodeURIComponent(pipelineId)}&owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&provider=${provider}`),
  cicdRuns: (owner?: string, repo?: string, branch?: string, status?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/runs?owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&branch=${encodeURIComponent(branch || "")}&status=${encodeURIComponent(status || "")}&provider=${provider}`),

  // ── Git ────────────────────────────────────────────────
  gitStatus: (repo?: string) => request<any>(`/api/git/status${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitBranch: (repo?: string) => request<any>(`/api/git/branch${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitBranches: (repo?: string) => request<{ branches: string[]; current: string }>(`/api/git/branches${repo ? `?repo=${encodeURIComponent(repo)}` : ""}`),
  gitLog: (count = 10, repo?: string) => request<any[]>(`/api/git/log?count=${count}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  gitDiff: (staged = false, repo?: string) => request<{ diff: string }>(`/api/git/diff?staged=${staged}${repo ? `&repo=${encodeURIComponent(repo)}` : ""}`),
  gitCommit: (message: string, auto = false, repo?: string) =>
    request<{ success: boolean; message: string; commit_hash: string; error: string }>("/api/git/commit", {
      method: "POST",
      body: JSON.stringify({ message, auto, repo }),
    }),
  gitPush: (repo?: string) => request<{ ok: boolean; output: string }>("/api/git/push", { method: "POST", body: JSON.stringify({ repo }) }),
  gitPull: (repo?: string) => request<{ ok: boolean; output: string }>("/api/git/pull", { method: "POST", body: JSON.stringify({ repo }) }),
  gitCheckout: (branch: string, create = false, repo?: string) =>
    request<{ ok: boolean; output: string; branch: string }>("/api/git/checkout", {
      method: "POST",
      body: JSON.stringify({ branch, create, repo }),
    }),
  gitCreatePr: (title: string, body = "", repo?: string) =>
    request<{ success: boolean; url: string; error: string }>("/api/git/pr", {
      method: "POST",
      body: JSON.stringify({ title, body, repo }),
    }),
  gitReview: (filePath = "", repo?: string) =>
    request<{ summary: string; comments: { file: string; line: number; severity: string; message: string }[] }>(
      "/api/git/review",
      { method: "POST", body: JSON.stringify({ file_path: filePath, repo }) },
    ),

  // ── Media ────────────────────────────────────────────
  mediaGenerate: (prompt: string, size = "1024x1024", quality = "standard") =>
    request<{ url: string; prompt: string; size: string; error?: string }>("/api/media/generate", {
      method: "POST",
      body: JSON.stringify({ prompt, size, quality }),
    }),
  mediaProcess: (filepath: string, opts?: { resize?: string; crop?: string; rotate?: number; flip?: string; output_format?: string; quality?: number }) =>
    request<{ format: string; width: number; height: number; bytes: number; data_url: string }>("/api/media/process", {
      method: "POST",
      body: JSON.stringify({ filepath, ...opts }),
    }),
  mediaParse: (filepath: string, pages?: string) =>
    request<{ text: string; truncated: boolean; metadata: Record<string, unknown> }>("/api/media/parse", {
      method: "POST",
      body: JSON.stringify({ filepath, pages }),
    }),
  mediaUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ path: string; size: number; filename: string }>("/api/media/upload", { method: "POST", body: form });
  },

  // ── Knowledge Graph ──────────────────────────────────
  knowledgeExtract: (text: string, source?: string) =>
    request<{ result: { entities: string[]; relations: string[] }; stats: Record<string, unknown> }>("/api/knowledge/extract", {
      method: "POST", body: JSON.stringify({ text, source }),
    }),
  knowledgeSearch: (query: string, max_depth = 2) =>
    request<{ results: any[]; stats: Record<string, unknown> }>("/api/knowledge/search", {
      method: "POST", body: JSON.stringify({ query, max_depth }),
    }),
  knowledgeStats: () => request<Record<string, unknown>>("/api/knowledge/stats"),
  knowledgeVis: () =>
    request<{ graph: { nodes: any[]; links: any[] }; stats: Record<string, unknown> }>("/api/knowledge/vis"),
  knowledgeAddEntity: (name: string, type = "concept", metadata = "") =>
    request<{ entity: { id: string; name: string; type: string } }>("/api/knowledge/entity", {
      method: "POST", body: JSON.stringify({ name, type, metadata }),
    }),
  knowledgeAddRelation: (source: string, target: string, type = "related_to") =>
    request<{ relation: { id: string; source: string; target: string; type: string } }>("/api/knowledge/relation", {
      method: "POST", body: JSON.stringify({ source, target, type }),
    }),

  // ── Voice Biometrics ─────────────────────────────
  voiceEnroll: (speaker_id: string, audio_samples: number[][], sample_rate = 16000) =>
    request<{ speaker_id: string; samples_processed: number; success: boolean }>("/api/voice/enroll", {
      method: "POST", body: JSON.stringify({ speaker_id, audio_samples, sample_rate }),
    }),
  voiceVerify: (speaker_id: string, audio: number[], sample_rate = 16000, anti_spoof = true) =>
    request<{ verified: boolean; score: number; threshold: number; speaker_id: string; latency_ms: number; anti_spoof_score: number | null; is_spoof: boolean }>("/api/voice/verify", {
      method: "POST", body: JSON.stringify({ speaker_id, audio, sample_rate, anti_spoof }),
    }),
  voiceIdentify: (audio: number[], sample_rate = 16000, top_k = 3) =>
    request<{ results: { speaker_id: string; score: number; verified: boolean; threshold: number }[] }>("/api/voice/identify", {
      method: "POST", body: JSON.stringify({ audio, sample_rate, top_k }),
    }),
  voiceSpeakers: () =>
    request<{ speakers: any[] }>("/api/voice/speakers"),
  voiceRemove: (speaker_id: string) =>
    request<{ success: boolean }>("/api/voice/remove", {
      method: "POST", body: JSON.stringify({ speaker_id }),
    }),
  voiceStats: () =>
    request<Record<string, any>>("/api/voice/stats"),
  voiceContinuousStart: (speaker_id: string, interval_sec = 5) =>
    request<{ success: boolean }>("/api/voice/continuous_start", {
      method: "POST", body: JSON.stringify({ speaker_id, interval_sec }),
    }),
  voiceContinuousStop: (speaker_id: string) =>
    request<{ success: boolean }>("/api/voice/continuous_stop", {
      method: "POST", body: JSON.stringify({ speaker_id }),
    }),

  // ── Collaboration ─────────────────────────────────
  collabCreateSession: (session_id: string, file_path: string) =>
    request<{ session_id: string; file_path: string }>("/api/collab/sessions", {
      method: "POST", body: JSON.stringify({ session_id, file_path }),
    }),
  collabSessions: () =>
    request<{ sessions: any[] }>("/api/collab/sessions"),
  collabSession: (id: string) =>
    request<any>(`/api/collab/sessions/${id}`),
  collabJoin: (session_id: string, user_id: string, user_name: string) =>
    request<any>(`/api/collab/sessions/${session_id}/join`, {
      method: "POST", body: JSON.stringify({ session_id, user_id, user_name }),
    }),
  collabLeave: (session_id: string, user_id: string) =>
    request<any>(`/api/collab/sessions/${session_id}/leave`, {
      method: "POST", body: JSON.stringify({ session_id, user_id }),
    }),
  collabApplyChange: (session_id: string, file: string, start_line: number, start_col: number, end_line: number, end_col: number, old_text: string, new_text: string) =>
    request<{ version: number; success: boolean }>(`/api/collab/sessions/${session_id}/changes`, {
      method: "POST", body: JSON.stringify({ session_id, file, start_line, start_col, end_line, end_col, old_text, new_text }),
    }),
  collabAddComment: (session_id: string, user_id: string, file: string, line: number, text: string) =>
    request<{ id: string; success: boolean }>(`/api/collab/sessions/${session_id}/comments`, {
      method: "POST", body: JSON.stringify({ session_id, user_id, file, line, text }),
    }),
  collabGetContent: (session_id: string) =>
    request<{ content: string; version: number }>(`/api/collab/sessions/${session_id}/content`),

  // ── RAG ──────────────────────────────────────────
  ragIndexText: (document_id: string, text: string, source = "", metadata = "") =>
    request<{ document_id: string; chunks: number }>("/api/rag/index", {
      method: "POST", body: JSON.stringify({ document_id, text, source, metadata }),
    }),
  ragSearch: (query: string, top_k = 5, include_images = true) =>
    request<{ results: any[] }>("/api/rag/search", {
      method: "POST", body: JSON.stringify({ query, top_k, include_images }),
    }),
  ragStats: () =>
    request<Record<string, any>>("/api/rag/stats"),
  ragRemoveDocument: (document_id: string) =>
    request<{ success: boolean }>("/api/rag/remove", {
      method: "POST", body: JSON.stringify({ document_id }),
    }),

  // ── Fine-Tuning ─────────────────────────────────
  finetuneDatasetStats: () =>
    request<any>("/api/finetune/dataset/stats"),
  finetuneAddConversation: (system_prompt = "", messages_json = "") =>
    request<{ success: boolean; total: number }>("/api/finetune/dataset/conversation", {
      method: "POST", body: JSON.stringify({ system_prompt, messages_json }),
    }),
  finetuneAddCode: (code: string, language = "", description = "") =>
    request<{ success: boolean; total: number }>("/api/finetune/dataset/code", {
      method: "POST", body: JSON.stringify({ code, language, description }),
    }),
  finetuneLoadModel: (model_type = "llama", use_lora = true, use_qlora = false) =>
    request<any>("/api/finetune/model/load", {
      method: "POST", body: JSON.stringify({ model_type, use_lora, use_qlora }),
    }),
  finetuneStartTraining: (epochs = 3, learning_rate = 2e-4, batch_size = 4) =>
    request<any>("/api/finetune/train", {
      method: "POST", body: JSON.stringify({ epochs, learning_rate, batch_size }),
    }),
  finetuneModelInfo: () =>
    request<any>("/api/finetune/model/info"),
  finetuneCheckpoints: () =>
    request<{ checkpoints: any[] }>("/api/finetune/checkpoints"),

  // ── Chaos Engineering ────────────────────────────
  chaosInject: (fault_type: string, target = "", duration_sec = 30, intensity = 0.5) =>
    request<any>("/api/chaos/inject", {
      method: "POST", body: JSON.stringify({ fault_type, target, duration_sec, intensity }),
    }),
  chaosRecover: (fault_id: string) =>
    request<any>("/api/chaos/recover", {
      method: "POST", body: JSON.stringify({ fault_id }),
    }),
  chaosRecoverAll: () =>
    request<{ recovered: number }>("/api/chaos/recover_all", { method: "POST" }),
  chaosActive: () =>
    request<{ active: any[] }>("/api/chaos/active"),
  chaosHistory: (fault_type = "") =>
    request<{ history: any[] }>(`/api/chaos/history${fault_type ? `?fault_type=${fault_type}` : ""}`),
  chaosRunExperiment: (name: string, faults_json: string, hypothesis = "") =>
    request<any>("/api/chaos/experiments", {
      method: "POST", body: JSON.stringify({ name, faults_json, hypothesis }),
    }),
  chaosExperimentReport: (experiment_id: string) =>
    request<any>(`/api/chaos/experiments/${experiment_id}/report`),
  chaosSummary: () =>
    request<any>("/api/chaos/resilience/summary"),

  // ── Browser ────────────────────────────────────────
  browserStatus: () => request<any>("/api/browser/status"),
  browserStart: () => request<any>("/api/browser/start", { method: "POST" }),
  browserStop: () => request<any>("/api/browser/stop", { method: "POST" }),
  browserNavigate: (url: string, waitUntil = "domcontentloaded", timeout = 30) =>
    request<any>("/api/browser/navigate", { method: "POST", body: JSON.stringify({ url, wait_until: waitUntil, timeout }) }),
  browserClick: (selector: string, timeout = 10) =>
    request<any>("/api/browser/click", { method: "POST", body: JSON.stringify({ selector, timeout }) }),
  browserFill: (selector: string, value: string, timeout = 10) =>
    request<any>("/api/browser/fill", { method: "POST", body: JSON.stringify({ selector, value, timeout }) }),
  browserScreenshot: (selector?: string, fullPage = false) =>
    request<any>("/api/browser/screenshot", { method: "POST", body: JSON.stringify({ selector, full_page: fullPage }) }),
  browserEvaluate: (script: string) =>
    request<any>("/api/browser/evaluate", { method: "POST", body: JSON.stringify({ script }) }),
  browserExtract: (url?: string) =>
    request<any>("/api/browser/extract", { method: "POST", body: JSON.stringify({ url }) }),
  browserVisualDiff: (urlA: string, urlB: string, fullPage = false) =>
    request<any>("/api/browser/visual-diff", { method: "POST", body: JSON.stringify({ url_a: urlA, url_b: urlB, full_page: fullPage }) }),
  browserTabList: () => request<any>("/api/browser/tabs"),
  browserTabNew: (url?: string) =>
    request<any>("/api/browser/tabs", { method: "POST", body: JSON.stringify({ url }) }),
  browserTitle: () => request<any>("/api/browser/title"),
  browserUrl: () => request<any>("/api/browser/url"),

  // ── Web Search ─────────────────────────────────────
  webSearch: (query: string, provider = "duckduckgo", maxResults = 10) =>
    request<any>("/api/web-search/search", { method: "POST", body: JSON.stringify({ query, provider, max_results: maxResults }) }),
  webSearchFailover: (query: string, maxResults = 10) =>
    request<any>("/api/web-search/failover", { method: "POST", body: JSON.stringify({ query, max_results: maxResults }) }),
  webSearchProviders: () => request<{ providers: any[] }>("/api/web-search/providers"),

  // ── Email ──────────────────────────────────────────
  emailSend: (to: string, subject: string, body: string) =>
    request<{ success: boolean; to: string; subject: string }>("/api/email/send", {
      method: "POST", body: JSON.stringify({ to, subject, body }),
    }),
  emailInbox: (limit = 10) =>
    request<{ emails: any[]; total: number }>(`/api/email/inbox?limit=${limit}`),
  emailConfig: () =>
    request<Record<string, any>>("/api/email/config"),
};