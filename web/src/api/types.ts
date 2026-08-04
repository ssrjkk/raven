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

export interface CostUsageRecord {
  id: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  duration_ms: number;
  timestamp: number;
}

export interface CostSummary {
  total_cost: number;
  total_tokens: number;
  period_hours: number;
  daily_cost: number;
  monthly_cost: number;
  total_calls: number;
  by_model: Record<string, { cost: number; calls: number; input_tokens: number; output_tokens: number }>;
}

export interface ChatSearchResult {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  session_name: string;
  created_at: string;
}

export interface PatternCheckInfo {
  id: string;
  name: string;
  severity: string;
  description: string;
  fix_hint: string;
}

export interface PatternViolation {
  file: string;
  line: number;
  column: number;
  pattern_id: string;
  severity: "error" | "warning" | "info";
  message: string;
  line_content: string;
  fix_hint: string;
}

export interface PatternRunResponse {
  files_checked: number;
  violations: PatternViolation[];
  total: number;
  by_severity: Record<"error" | "warning" | "info", number>;
}

export interface ProjectMetrics {
  total_files: number;
  total_lines: number;
  code_lines: number;
  languages: number;
  language_breakdown: { language: string; files: number; lines: number; code_lines: number }[];
  top_dependencies: { module: string; count: number }[];
  dependency_count: number;
  activity: { today: number; this_week: number; this_month: number };
}

export interface ProjectInsightsData {
  project_id: string;
  time_saved_minutes: number;
  ai_contribution_percent: number;
  success_rate: number;
  token_cost_estimate: number;
  files: number;
  code_lines: number;
  commits: number;
  active_days: number;
  trend: { date: string; commits: number }[];
  generated_at: string;
}

export interface ThemeScheme {
  name: string;
  description: string;
  accent: string;
  palette: Record<string, Record<string, string>>;
}

export interface TruthfulResult {
  status: "success" | "corrected" | "refused";
  content: string;
  thinking_process: string;
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
  type: "message" | "stream" | "agent_status";
  role: string;
  content: string;
  session_id: string;
  event?: string;
  profile?: string;
  detail?: string;
  data?: Record<string, unknown>;
}

export interface AuthData {
  token: string;
  user: { id: string; role: string };
}

export interface GitHubUser {
  login: string;
  avatar_url: string;
  public_repos: number;
}

export interface GitHubRepo {
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

export interface GitHubBranch {
  name: string;
  commit: { sha: string };
}

export interface GitHubPull {
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

export interface GitHubContentItem {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
  sha: string;
}

export interface GitHubFileEntry extends GitHubContentItem {
  content: string;
  encoding: string;
}

export interface GitHubIssue {
  number: number;
  title: string;
  state: string;
  user: { login: string };
  created_at: string;
  labels: { name: string; color: string }[];
}

export interface GitHubTokenStatus {
  configured: boolean;
}

export interface GitHubReview {
  id: number;
  user: { login: string };
  body: string;
  state: string;
}

export interface GitHubComment {
  id: number;
  user: { login: string };
  body: string;
  created_at: string;
}

export interface GitHubSearchReposResult {
  items: GitHubRepo[];
  total_count: number;
}

export interface GitHubSearchCodeResult {
  items: { path: string; name: string }[];
  total_count: number;
}

export interface GitHubFileTreeItem {
  name: string;
  path: string;
  type: "file" | "dir";
}

export interface GitHubCloneResult {
  path: string;
}

export interface GitHubMergeResult {
  sha: string;
  merged: boolean;
  message: string;
}

export interface GitHubCreateResult {
  number: number;
  html_url: string;
}

export interface GitHubRateLimit {
  rate: { limit: number; remaining: number; reset: number; used: number };
}

export interface GitHubWorkflowDispatch {
  ok: boolean;
}

export interface AnalyticsTimePoint {
  ts: number;
  avg: number;
  max: number;
}

export interface AnalyticsRangeData {
  received?: number;
  errors?: number;
  error_rate?: number;
  message_series?: AnalyticsTimePoint[];
  error_series?: AnalyticsTimePoint[];
  latency_series?: Record<string, AnalyticsTimePoint[]>;
}

export interface AnalyticsFullData {
  last_hour?: AnalyticsRangeData;
  last_24h?: AnalyticsRangeData;
  summary?: { metrics: { name: string; avg: number; max: number; samples: number }[] };
  tool_breakdown?: { total: number; success_series?: AnalyticsTimePoint[]; error_series?: AnalyticsTimePoint[] };
  tool_usage_1h?: { name: string; total: number }[];
  tool_usage?: { name: string; total: number }[];
}

export interface AnalyticsSeriesData {
  metric: string;
  data: AnalyticsTimePoint[];
}

export interface AnalyticsSummaryData {
  metrics: { name: string; avg: number; max: number; samples: number }[];
}

export interface AnalyticsAggregatedData {
  metrics: Record<string, number>;
}

export interface AnalyticsToolUsageData {
  tools: { name: string; total: number; category?: string }[];
}

export interface AnalyticsToolBreakdownData {
  total: number;
  by_tool: Record<string, { calls: number; errors: number }>;
  success_series?: AnalyticsTimePoint[];
  error_series?: AnalyticsTimePoint[];
}

export interface PricingInfo {
  input_per_1k: number;
  output_per_1k: number;
}

export interface BudgetInfo {
  id: string;
  name: string;
  daily_limit: number;
  monthly_limit: number;
  current_daily?: number;
  current_monthly?: number;
  spent?: number;
}

export interface CostBudgetCreateResult {
  id: string;
  name: string;
}

export interface CostCheckResult {
  within_budget: boolean;
  exceeded_daily?: boolean;
  exceeded_monthly?: boolean;
}

export interface ABTestVariant {
  id: string;
  name: string;
  weight: number;
  config: Record<string, unknown>;
}

export interface ABTestData {
  id: string;
  name: string;
  description?: string;
  status: string;
  variants: ABTestVariant[];
  metric?: string;
  created_at: string;
}

export interface ABTestResults {
  total_events: number;
  significance: number;
  significant: boolean;
  variants: { name: string; lift: number; events: number; avg_value: number; sample_count: number }[];
}

export interface ABCreateResponse {
  id: string;
  name: string;
}

export interface PluginInfo {
  id?: string;
  name: string;
  version: string;
  description?: string;
  author?: string;
  category?: string;
  status?: string;
  installed_at?: string;
  rating?: number;
  tags?: string[];
}

export interface CollabUserInfo {
  id: string;
  name: string;
}

export interface CollabSessionInfo {
  session_id: string;
  file_path: string;
  connected_users: number;
  users: number | CollabUserInfo[];
  version: string;
}

export interface CollabSessionDetails extends CollabSessionInfo {
  content?: string;
  comments?: { id: string; user_id: string; line: number; text: string; resolved: boolean }[];
}

export interface KnowledgeSearchEntry {
  id: string;
  name: string;
  type: string;
  neighbors?: { entity: string; relation: string; type: string }[];
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export interface GraphLink {
  source: string;
  target: string;
  relation: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface VoiceSpeakerInfo {
  speaker_id: string;
  num_samples: number;
}

export interface VoiceStatsData {
  enrolled_speakers?: number;
  continuous_sessions?: number;
  threshold?: number;
  encoder_model?: string;
}

export interface RAGResultEntry {
  modality?: string;
  score: number;
  document_id?: string;
  text?: string;
  image_path?: string;
}

export interface RAGStatsData {
  documents?: number;
  chunks?: number;
  total_chars?: number;
  total_images?: number;
  dimension?: number;
  sentence_transformer?: boolean;
  clip_available?: boolean;
  chroma_available?: boolean;
}

export interface DatasetStatsData {
  conversations?: number;
  code_samples?: number;
  config?: { max_length?: number };
}

export interface ModelInfoData {
  model_name?: string;
  model_type?: string;
  trainable_params?: number;
  total_params?: number;
}

export interface CheckpointData {
  step?: number;
  epoch?: number;
  path?: string;
}

export interface TrainingResultData {
  train_loss?: number;
  global_step?: number;
  epoch?: number;
  eval_loss?: number;
  eval_perplexity?: number;
}

export interface ChaosFaultConfigInfo {
  fault_type: string;
  target?: string;
  duration_sec?: number;
  intensity?: number;
}

export interface ChaosFaultInfo {
  id: string;
  config?: ChaosFaultConfigInfo;
  recovered?: boolean;
}

export interface ChaosExperimentResult {
  status: string;
  resilience_score?: number;
  hypothesis_validated?: boolean;
  faults_injected?: number;
  faults_recovered?: number;
  experiment_id?: string;
}

export interface ChaosSummaryReport {
  experiments_run: number;
  avg_resilience?: number;
  avg_steadiness?: number;
  hypotheses_validated?: number;
}

export interface BrowserStatusData {
  running: boolean;
  url?: string;
  title?: string;
}

export interface BrowserActionResult {
  success: boolean;
  message?: string;
}

export interface BrowserScreenshotResult {
  data: string;
  mime: string;
}

export interface BrowserEvaluateResult {
  result: unknown;
}

export interface BrowserExtractResult {
  text: string;
  title: string;
  url: string;
}

export interface BrowserVisualDiffResult {
  diff: string;
  diff_percent: number;
  passed: boolean;
}

export interface BrowserTabInfo {
  id: string;
  url: string;
  title: string;
}

export interface BrowserTitleResult {
  title: string;
}

export interface BrowserUrlResult {
  url: string;
}

export interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
}

export interface WebSearchProvider {
  name: string;
  enabled: boolean;
}

export interface EmailThreadEntry {
  from: string;
  subject: string;
  date?: string;
  body_preview?: string;
}

export interface EmailConfigInfo {
  smtp_configured?: boolean;
  smtp_host?: string;
  imap_configured?: boolean;
  imap_host?: string;
  smtp_lib_available?: boolean;
  imap_lib_available?: boolean;
}

export interface OAuthProviderInfo {
  name: string;
  icon: string;
  enabled: boolean;
}

export interface GitStatusData {
  branch?: string;
  changed_files?: number;
  is_repo?: boolean;
  is_branch?: boolean;
  changes: string[];
}

export interface GitBranchInfo {
  current: string;
}

export interface GitCommitEntry {
  hash: string;
  message: string;
  author: string;
  date: string;
}

export interface DiffFileInfo {
  path: string;
  added: number;
  deleted: number;
  hunks: { oldStart: number; newStart: number; lines: string[] }[];
}

export interface GitCommitDetail {
  hash: string;
  message: string;
  author: string;
  author_email?: string;
  date: string;
  diff: string;
  files?: DiffFileInfo[];
  total_files: number;
  total_added: number;
  total_deleted: number;
  error?: string;
}

export interface BlameLineData {
  hash: string;
  author: string;
  content: string;
}

export interface DebugFrame {
  filename: string;
  function: string;
  line: number;
  locals: Record<string, string>;
}

export interface DebugState {
  status: string;
  paused_file: string | null;
  paused_line: number | null;
  frames: DebugFrame[];
  error: string | null;
}

export interface GitBlameResult {
  lines: BlameLineData[];
  file: string;
  error?: string;
}

export interface DreamSkillEntry {
  name: string;
  description: string;
  source: string;
}

export interface DreamMemoryStats {
  working: number;
  session: number;
  long_term: number;
  knowledge: number;
}

export interface DreamStatusData {
  running: boolean;
  total_cycles: number;
  last_cycle_time: number;
  last_cycle_stats: Record<string, number> | null;
  idle_timeout: number;
  cycle_interval: number;
}

export interface DreamStatsData extends DreamStatusData {
  memory: DreamMemoryStats;
  skills: DreamSkillEntry[];
}
