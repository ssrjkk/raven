import { analyticsApi } from "./analytics";
import { browserApi } from "./browser";
import { gitApi } from "./git";
import { githubApi } from "./github";
import type {
ABCreateResponse,
ABTestData, ABTestResults, AuthData,   BrowserActionResult, ChannelInfo, ChaosExperimentResult, ChaosFaultInfo, ChaosSummaryReport,
  ChatSearchResult,   CheckpointData, CodingSessionData, CollabSessionDetails,   CollabSessionInfo, DatasetStatsData, DebugState,
EmailConfigInfo,
EmailThreadEntry, GraphData,
DreamStatsData, DreamStatusData,
HealthData, KnowledgeSearchEntry, MessageData, MetricsSnapshot, ModelInfoData,
MonitorData,
OAuthProviderInfo, PatternCheckInfo, PatternRunResponse,
PluginInfo, RAGResultEntry, RAGStatsData,   RoutineData, Session,   StatusData, TaskData, TrainingResultData,   VoiceSpeakerInfo, VoiceStatsData, WebSearchProvider,   WebSearchResult, } from "./types";

export type {
ABCreateResponse,
ABTestData, ABTestResults,   ABTestVariant, AnalyticsAggregatedData, AnalyticsFullData, AnalyticsRangeData, AnalyticsSeriesData,
  AnalyticsSummaryData,   AnalyticsTimePoint, AnalyticsToolBreakdownData,
AnalyticsToolUsageData, AuthData,
  BlameLineData, BrowserActionResult, BrowserEvaluateResult,
  BrowserExtractResult, BrowserScreenshotResult,   BrowserStatusData, BrowserTabInfo, BrowserTitleResult, BrowserUrlResult,
BrowserVisualDiffResult, BudgetInfo, ChannelInfo, ChaosExperimentResult,   ChaosFaultConfigInfo, ChaosFaultInfo, ChaosSummaryReport,
ChatSearchResult,
CheckpointData, CodingSessionData, CollabSessionDetails,
CollabSessionInfo, CollabUserInfo, CostBudgetCreateResult, CostCheckResult,
CostSummary, CostUsageRecord,   DatasetStatsData, DebugFrame,
  DebugState, DiffFileInfo, DreamMemoryStats, DreamSkillEntry, DreamStatsData, DreamStatusData,
EmailConfigInfo, EmailThreadEntry, GitBlameResult,
GitBranchInfo, GitCommitDetail, GitCommitEntry, GitHubBranch, GitHubCloneResult, GitHubComment, GitHubContentItem,   GitHubCreateResult, GitHubFileEntry,
GitHubFileTreeItem,   GitHubIssue, GitHubMergeResult,
GitHubPull, GitHubRateLimit, GitHubRepo, GitHubReview,   GitHubSearchCodeResult, GitHubSearchReposResult,
GitHubTokenStatus,   GitHubUser, GitHubWorkflowDispatch,
  GitStatusData, GraphData,
GraphLink, GraphNode, HealthCheck, HealthData,   KnowledgeSearchEntry, MessageData, MetricsSnapshot, ModelInfoData, MonitorData,
OAuthProviderInfo,
  PatternCheckInfo, PatternRunResponse, PatternViolation,   PluginInfo,   PricingInfo, ProjectMetrics,
RAGResultEntry, RAGStatsData,
  RoutineData,   Session,   StatusData, TaskData, TrainingResultData,
  VoiceSpeakerInfo, VoiceStatsData, WebSearchProvider,   WebSearchResult, WsMessage, } from "./types";

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
  if (init?.headers) {
    const incoming = init.headers as Record<string, string>;
    for (const [k, v] of Object.entries(incoming)) {
      headers[k] = v;
    }
  }
  const controller = new AbortController();
  const { signal: externalSignal, ...safeInit } = init ?? {};
  if (externalSignal) {
    externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers,
      signal: controller.signal,
      ...safeInit,
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
  monitors: (limit = 50, offset = 0) =>
    request<{ items: MonitorData[]; total: number; limit: number; offset: number }>(`/api/monitor/list?limit=${limit}&offset=${offset}`).then((r) => r.items),
  monitorToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/monitor/${action}/${id}`, { method: "POST" }),
  routines: (limit = 50, offset = 0) =>
    request<{ items: RoutineData[]; total: number; limit: number; offset: number }>(`/api/routine/list?limit=${limit}&offset=${offset}`).then((r) => r.items),
  routineToggle: (action: string, id: string) => request<{ ok: boolean }>(`/api/routine/${action}/${id}`, { method: "POST" }),
  routineCreate: (data: { name?: string; action?: string; schedule?: string; trigger?: string; config?: Record<string, unknown> }) =>
    request<{ ok: boolean; id: string }>("/api/routine/create", { method: "POST", body: JSON.stringify(data) }),
  routineDelete: (id: string) => request<{ ok: boolean }>(`/api/routine/${id}`, { method: "DELETE" }),
  tasks: (limit = 50, offset = 0) =>
    request<{ items: TaskData[]; total: number; limit: number; offset: number }>(`/api/task/list?limit=${limit}&offset=${offset}`).then((r) => r.items),
  taskRun: (goal: string) => request<{ id: string }>("/api/task/run", { method: "POST", body: JSON.stringify({ goal }) }),
  taskCancel: (id: string) => request<{ ok: boolean }>(`/api/task/${id}/cancel`, { method: "POST" }),
  codeSessions: (limit = 20, offset = 0) =>
    request<{ items: CodingSessionData[]; total: number; limit: number; offset: number }>(`/api/code/list?limit=${limit}&offset=${offset}`).then((r) => r.items),
  config: () => request<Record<string, string>>("/api/admin/config"),
  shutdown: () => request<{ ok: boolean }>("/api/shutdown", { method: "POST" }),
  login: (username: string, password: string) =>
    request<AuthData>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string) =>
    request<AuthData>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
  workflowInstantiate: (templateId: string, config?: Record<string, unknown>) =>
    request<{ ok: boolean; task_id: string }>(`/api/admin/workflows/${templateId}/instantiate`, { method: "POST", body: JSON.stringify({ config: config || {} }) }),
  workflowSchedule: (templateId: string, config?: Record<string, unknown>) =>
    request<{ ok: boolean; routine_id: string }>(`/api/admin/workflows/${templateId}/schedule`, { method: "POST", body: JSON.stringify({ config: config || {} }) }),

  plugins: () => request<PluginInfo[]>("/api/plugins"),
  pluginsCatalog: (category?: string) =>
    request<PluginInfo[]>(`/api/plugins/catalog${category ? `?category=${encodeURIComponent(category)}` : ""}`),
  pluginsSearch: (q: string) => request<PluginInfo[]>(`/api/plugins/search?q=${encodeURIComponent(q)}`),
  pluginsInstall: (url: string) =>
    request<{ ok?: boolean; error?: string; name?: string; version?: string }>("/api/plugins/install", {
      method: "POST", body: JSON.stringify({ url }),
    }),
  pluginsUninstall: (name: string) =>
    request<{ ok?: boolean; error?: string }>(`/api/plugins/uninstall/${encodeURIComponent(name)}`, { method: "POST" }),
  pluginsUpdate: (name: string) =>
    request<{ ok?: boolean; error?: string }>(`/api/plugins/update/${encodeURIComponent(name)}`, { method: "POST" }),
  pluginsTop: (limit = 10) => request<PluginInfo[]>(`/api/plugins/top?limit=${limit}`),

  oauthProviders: () => request<{ providers: OAuthProviderInfo[] }>("/api/admin/auth/oauth/providers"),
  oauthAuthorize: (provider: string, redirectUri = "") =>
    request<{ url: string }>(`/api/admin/auth/oauth/authorize/${provider}?redirect_uri=${encodeURIComponent(redirectUri)}`),
  oauthCallback: (provider: string, code: string, state: string) =>
    request<{ token: string; user: { id: string; role: string } }>(`/api/admin/auth/oauth/callback/${provider}`, { method: "POST", body: JSON.stringify({ code, state }) }),

  patternChecks: () => request<PatternCheckInfo[]>("/api/v1/patterns/checks"),
  patternRun: (file?: string, checkIds?: string) => request<PatternRunResponse>(`/api/v1/patterns/run${file ? `?file=${encodeURIComponent(file)}` : ""}${checkIds ? `${file ? "&" : "?"}check_ids=${encodeURIComponent(checkIds)}` : ""}`),

  chatSearch: (q: string, limit = 50) => request<{ results: ChatSearchResult[]; total: number; query: string }>(`/api/chat/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  abCreate: (name: string, description: string, variantsJson: string, metricName = "conversion") =>
    request<ABCreateResponse>("/api/ab/experiments", {
      method: "POST", body: JSON.stringify({ name, description, variants_json: variantsJson, metric_name: metricName }),
    }),
  abExperiments: () => request<{ experiments: ABTestData[] }>("/api/ab/experiments"),
  abGet: (id: string) => request<ABTestData>(`/api/ab/experiments/${id}`),
  abStatus: (id: string, status: string) =>
    request<{ ok: boolean }>(`/api/ab/experiments/${id}/status`, { method: "POST", body: JSON.stringify({ status }) }),
  abDelete: (id: string) => request<{ ok: boolean }>(`/api/ab/experiments/${id}`, { method: "DELETE" }),
  abResults: (id: string) => request<ABTestResults>(`/api/ab/experiments/${id}/results`),
  abAssign: (id: string, userId = "") =>
    request<{ variant: string }>(`/api/ab/experiments/${id}/assign`, { method: "POST", body: JSON.stringify({ user_id: userId }) }),
  abRecord: (id: string, variant: string, metricName = "conversion", value = 1.0, userId = "") =>
    request<{ ok: boolean }>(`/api/ab/experiments/${id}/record`, {
      method: "POST", body: JSON.stringify({ variant, metric_name: metricName, value, user_id: userId }),
    }),

  testsRun: (path?: string, marker?: string, timeout = 120, extraArgs = "") =>
    request<{ text: string }>("/api/tests/run", {
      method: "POST", body: JSON.stringify({ path, marker, timeout, extra_args: extraArgs }),
    }),
  testsCoverage: (path?: string, timeout = 180) =>
    request<{ text: string }>("/api/tests/coverage", { method: "POST", body: JSON.stringify({ path, timeout }) }),
  testsGenerate: (filePath: string) =>
    request<{ text: string }>("/api/tests/generate", { method: "POST", body: JSON.stringify({ file_path: filePath }) }),

  cicdWorkflows: (owner?: string, repo?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/workflows?owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&provider=${provider}`),
  cicdRun: (workflowId: string, owner?: string, repo?: string, ref = "main", inputs = "", provider = "github") =>
    request<{ text: string }>("/api/cicd/run", {
      method: "POST", body: JSON.stringify({ workflow_id: workflowId, owner, repo, ref, inputs, provider }),
    }),
  cicdStatus: (pipelineId: string, owner?: string, repo?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/status?pipeline_id=${encodeURIComponent(pipelineId)}&owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&provider=${provider}`),
  cicdRuns: (owner?: string, repo?: string, branch?: string, status?: string, provider = "github") =>
    request<{ text: string }>(`/api/cicd/runs?owner=${encodeURIComponent(owner || "")}&repo=${encodeURIComponent(repo || "")}&branch=${encodeURIComponent(branch || "")}&status=${encodeURIComponent(status || "")}&provider=${provider}`),

  mediaGenerate: (prompt: string, size = "1024x1024", quality = "standard") =>
    request<{ url: string; prompt: string; size: string; error?: string }>("/api/media/generate", {
      method: "POST", body: JSON.stringify({ prompt, size, quality }),
    }),
  mediaProcess: (filepath: string, opts?: { resize?: string; crop?: string; rotate?: number; flip?: string; output_format?: string; quality?: number }) =>
    request<{ format: string; width: number; height: number; bytes: number; data_url: string }>("/api/media/process", {
      method: "POST", body: JSON.stringify({ filepath, ...opts }),
    }),
  mediaParse: (filepath: string, pages?: string) =>
    request<{ text: string; truncated: boolean; metadata: Record<string, unknown> }>("/api/media/parse", {
      method: "POST", body: JSON.stringify({ filepath, pages }),
    }),
  mediaUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ path: string; size: number; filename: string }>("/api/media/upload", { method: "POST", body: form });
  },

  knowledgeExtract: (text: string, source?: string) =>
    request<{ result: { entities: string[]; relations: string[] }; stats: Record<string, unknown> }>("/api/knowledge/extract", {
      method: "POST", body: JSON.stringify({ text, source }),
    }),
  knowledgeSearch: (query: string, max_depth = 2) =>
    request<{ results: KnowledgeSearchEntry[]; stats: Record<string, unknown> }>("/api/knowledge/search", {
      method: "POST", body: JSON.stringify({ query, max_depth }),
    }),
  knowledgeStats: () => request<Record<string, unknown>>("/api/knowledge/stats"),
  knowledgeVis: () => request<{ graph: GraphData; stats: Record<string, unknown> }>("/api/knowledge/vis"),
  knowledgeAddEntity: (name: string, type = "concept", metadata = "") =>
    request<{ entity: { id: string; name: string; type: string } }>("/api/knowledge/entity", {
      method: "POST", body: JSON.stringify({ name, type, metadata }),
    }),
  knowledgeAddRelation: (source: string, target: string, type = "related_to") =>
    request<{ relation: { id: string; source: string; target: string; type: string } }>("/api/knowledge/relation", {
      method: "POST", body: JSON.stringify({ source, target, type }),
    }),

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
  voiceSpeakers: () => request<{ speakers: VoiceSpeakerInfo[] }>("/api/voice/speakers"),
  voiceRemove: (speaker_id: string) =>
    request<{ success: boolean }>("/api/voice/remove", { method: "POST", body: JSON.stringify({ speaker_id }) }),
  voiceStats: () => request<VoiceStatsData>("/api/voice/stats"),
  voiceContinuousStart: (speaker_id: string, interval_sec = 5) =>
    request<{ success: boolean; speaker_id: string; interval_sec: number }>("/api/voice/continuous_start", {
      method: "POST", body: JSON.stringify({ speaker_id, interval_sec }),
    }),
  voiceContinuousStop: (speaker_id: string) =>
    request<{ success: boolean }>("/api/voice/continuous_stop", { method: "POST", body: JSON.stringify({ speaker_id }) }),

  collabCreateSession: (session_id: string, file_path: string) =>
    request<{ session_id: string; file_path: string }>("/api/collab/sessions", {
      method: "POST", body: JSON.stringify({ session_id, file_path }),
    }),
  collabSessions: () => request<{ sessions: CollabSessionInfo[] }>("/api/collab/sessions"),
  collabSession: (id: string) => request<CollabSessionDetails>(`/api/collab/sessions/${id}`),
  collabJoin: (session_id: string, user_id: string, user_name: string) =>
    request<{ ok: boolean }>(`/api/collab/sessions/${session_id}/join`, {
      method: "POST", body: JSON.stringify({ session_id, user_id, user_name }),
    }),
  collabLeave: (session_id: string, user_id: string) =>
    request<{ ok: boolean }>(`/api/collab/sessions/${session_id}/leave`, {
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

  ragIndexText: (document_id: string, text: string, source = "", metadata = "") =>
    request<{ document_id: string; chunks: number }>("/api/rag/index", {
      method: "POST", body: JSON.stringify({ document_id, text, source, metadata }),
    }),
  ragSearch: (query: string, top_k = 5, include_images = true) =>
    request<{ results: RAGResultEntry[] }>("/api/rag/search", {
      method: "POST", body: JSON.stringify({ query, top_k, include_images }),
    }),
  ragStats: () => request<RAGStatsData>("/api/rag/stats"),
  ragRemoveDocument: (document_id: string) =>
    request<{ success: boolean }>("/api/rag/remove", { method: "POST", body: JSON.stringify({ document_id }) }),

  finetuneDatasetStats: () => request<DatasetStatsData>("/api/finetune/dataset/stats"),
  finetuneAddConversation: (system_prompt = "", messages_json = "") =>
    request<{ success: boolean; total: number }>("/api/finetune/dataset/conversation", {
      method: "POST", body: JSON.stringify({ system_prompt, messages_json }),
    }),
  finetuneAddCode: (code: string, language = "", description = "") =>
    request<{ success: boolean; total: number }>("/api/finetune/dataset/code", {
      method: "POST", body: JSON.stringify({ code, language, description }),
    }),
  finetuneLoadModel: (model_type = "llama", use_lora = true, use_qlora = false) =>
    request<ModelInfoData>("/api/finetune/model/load", {
      method: "POST", body: JSON.stringify({ model_type, use_lora, use_qlora }),
    }),
  finetuneStartTraining: (epochs = 3, learning_rate = 2e-4, batch_size = 4) =>
    request<TrainingResultData>("/api/finetune/train", {
      method: "POST", body: JSON.stringify({ epochs, learning_rate, batch_size }),
    }),
  finetuneModelInfo: () => request<ModelInfoData>("/api/finetune/model/info"),
  finetuneCheckpoints: () => request<{ checkpoints: CheckpointData[] }>("/api/finetune/checkpoints"),

  chaosInject: (fault_type: string, target = "", duration_sec = 30, intensity = 0.5) =>
    request<{ id: string }>("/api/chaos/inject", {
      method: "POST", body: JSON.stringify({ fault_type, target, duration_sec, intensity }),
    }),
  chaosRecover: (fault_id: string) =>
    request<{ ok: boolean }>("/api/chaos/recover", { method: "POST", body: JSON.stringify({ fault_id }) }),
  chaosRecoverAll: () => request<{ recovered: number }>("/api/chaos/recover_all", { method: "POST" }),
  chaosActive: () => request<{ active: ChaosFaultInfo[] }>("/api/chaos/active"),
  chaosHistory: (fault_type = "") =>
    request<{ history: ChaosFaultInfo[] }>(`/api/chaos/history${fault_type ? `?fault_type=${fault_type}` : ""}`),
  chaosRunExperiment: (name: string, faults_json: string, hypothesis = "") =>
    request<ChaosExperimentResult>("/api/chaos/experiments", {
      method: "POST", body: JSON.stringify({ name, faults_json, hypothesis }),
    }),
  chaosExperimentReport: (experiment_id: string) =>
    request<ChaosExperimentResult>(`/api/chaos/experiments/${experiment_id}/report`),
  chaosSummary: () => request<ChaosSummaryReport>("/api/chaos/resilience/summary"),

  webSearch: (query: string, provider = "duckduckgo", maxResults = 10) =>
    request<{ results: WebSearchResult[] }>("/api/web-search/search", { method: "POST", body: JSON.stringify({ query, provider, max_results: maxResults }) }),
  webSearchFailover: (query: string, maxResults = 10) =>
    request<{ results: WebSearchResult[] }>("/api/web-search/failover", { method: "POST", body: JSON.stringify({ query, max_results: maxResults }) }),
  webSearchProviders: () => request<{ providers: WebSearchProvider[] }>("/api/web-search/providers"),

  emailSend: (to: string, subject: string, body: string) =>
    request<{ success: boolean; to: string; subject: string }>("/api/email/send", {
      method: "POST", body: JSON.stringify({ to, subject, body }),
    }),
  emailInbox: (limit = 10) => request<{ emails: EmailThreadEntry[]; total: number }>(`/api/email/inbox?limit=${limit}`),
  emailConfig: () => request<EmailConfigInfo>("/api/email/config"),

  getTheme: () => request<{ accentColor: string }>("/api/v1/commands/theme"),
  saveTheme: (accentColor: string) =>
    request<{ accentColor: string }>("/api/v1/commands/theme", {
      method: "POST", body: JSON.stringify({ accentColor }),
    }),

  scaffoldPlans: () =>
    request<{ id: string; name: string; description: string; questions: { key: string; label: string; default: string | boolean | number; type: string; options?: string[] }[] }[]>("/api/v1/scaffold/plans"),
  scaffoldGenerate: (templateId: string, answers: Record<string, string | boolean | number>, outputDir: string) =>
    request<{ files: { path: string; content?: string }[]; tree: string }>("/api/v1/scaffold/generate", { method: "POST", body: JSON.stringify({ template_id: templateId, answers, output_dir: outputDir }) }),

  insightsCoding: (days: number) =>
    request<{ total_commits: number; total_days_active: number; avg_commits_per_day: number; commits_per_day: { date: string; count: number }[]; peak_hours: { hour: number; count: number }[]; top_files: { path: string; changes: number }[] }>(`/api/insights/coding?days=${days}`),
  insightsLlm: (days: number) =>
    request<{ total_calls: number; total_cost: number; total_tokens: number; avg_cost_per_call: number; calls_per_day: { date: string; calls: number; cost: number; tokens: number }[]; models: { model: string; calls: number }[]; peak_hours: { hour: number; calls: number }[] }>(`/api/insights/llm?days=${days}`),
  insightsWorkspace: () =>
    request<{ total_files: number; total_dirs: number; by_extension: Record<string, number>; largest_files: { path: string; size_bytes: number }[]; recently_modified: { path: string; modified_at: string }[] }>("/api/insights/workspace"),

  ideAgentRun: (task: string, mode: string, workspace: string) =>
    request<{ response?: string }>("/api/v1/agent/run", { method: "POST", body: JSON.stringify({ task, mode, workspace }) }),
  ideContextIndex: (workspace: string) =>
    request<{ indexed: number }>("/api/v1/context/index", { method: "POST", body: JSON.stringify({ workspace }) }),
  ideContextSearch: (query: string, topK = 5) =>
    request<{ results: { content: string; file: string; score: number }[] }>("/api/v1/context/search", { method: "POST", body: JSON.stringify({ query, top_k: topK }) }),
  ideAgentExecute: (command: string, context: string) =>
    request<{ output?: string; error?: string }>("/api/v1/agent/execute", { method: "POST", body: JSON.stringify({ command, context }) }),

  mediaAnalyze: (filepath: string, prompt: string) =>
    request<{ result?: string }>("/api/media/analyze", { method: "POST", body: JSON.stringify({ filepath, prompt }) }),
  mediaVideoInfo: (filepath: string) =>
    request<{ result?: string }>("/api/media/video-info", { method: "POST", body: JSON.stringify({ filepath }) }),
  mediaVideoThumbnail: (filepath: string, timeSec = 1, size = "320x240") =>
    request<{ result?: string }>("/api/media/video-thumbnail", { method: "POST", body: JSON.stringify({ filepath, time_sec: timeSec, size }) }),
  mediaVideoTranscribe: (filepath: string, language?: string) =>
    request<{ result?: string }>("/api/media/video-transcribe", { method: "POST", body: JSON.stringify({ filepath, language }) }),
  mediaVideoExtractFrames: (filepath: string, intervalSec = 5, maxFrames = 10, size = "320x240") =>
    request<{ result?: string }>("/api/media/video-extract-frames", { method: "POST", body: JSON.stringify({ filepath, interval_sec: intervalSec, max_frames: maxFrames, size }) }),

  browserTabSwitch: (index: number) =>
    request<BrowserActionResult>("/api/browser/tabs/switch", { method: "POST", body: JSON.stringify({ index }) }),
  browserTabClose: () =>
    request<BrowserActionResult>("/api/browser/tabs/close", { method: "POST" }),
  browserIntercept: (action: string) =>
    request<BrowserActionResult>("/api/browser/intercept", { method: "POST", body: JSON.stringify({ action }) }),
  browserRequests: () => request<unknown[]>("/api/browser/requests"),
  browserResponses: () => request<unknown[]>("/api/browser/responses"),

  debugState: () => request<DebugState>("/api/debug/state"),
  debugStart: (file: string, breakpoints: { file: string; line: number; enabled: boolean }[]) =>
    request<DebugState>("/api/debug/start", { method: "POST", body: JSON.stringify({ file, breakpoints }) }),
  debugStop: () => request<DebugState>("/api/debug/stop", { method: "POST" }),
  debugStepOver: () => request<DebugState>("/api/debug/step-over", { method: "POST" }),
  debugStepInto: () => request<DebugState>("/api/debug/step-into", { method: "POST" }),
  debugContinue: () => request<DebugState>("/api/debug/continue", { method: "POST" }),

  workflowsList: () =>
    request<{ id: string; name: string; description: string; category: string; trigger: string; icon: string; default_schedule: string | null; default_interval: number | null; config_schema: { properties?: Record<string, { title?: string; type?: string; default?: string }> }; predefined_steps: { description: string; tool: string | null; params: Record<string, string> }[]; steps_goal: string | null; system_prompt: string | null }[]>("/api/admin/workflows"),
  workflowCategories: () => request<{ categories: string[] }>("/api/admin/workflow-categories"),
  workflowRuns: () => request<{ runs: { id: string; template_id: string; template_name: string; status: string; started_at: string }[] }>("/api/admin/workflow-runs"),
  workflowSteps: (id: string, steps: { description: string; tool: string | null; params: Record<string, string> }[]) =>
    request<unknown>(`/api/admin/workflows/${id}/steps`, { method: "PUT", body: JSON.stringify({ steps }) }),
  workflowGenerateSteps: (id: string) =>
    request<{ steps: { description: string; tool: string | null; params: Record<string, string> }[] }>(`/api/admin/workflows/${id}/generate-steps`, { method: "POST" }),

  dreamStatus: () => request<DreamStatusData>("/api/dream/status"),
  dreamStats: () => request<DreamStatsData>("/api/dream/stats"),
  dreamCycle: () => request<{ ok: boolean; stats: Record<string, number> }>("/api/dream/cycle", { method: "POST" }),

  ...githubApi,
  ...analyticsApi,
  ...browserApi,
  ...gitApi,
};
