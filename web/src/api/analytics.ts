import { request } from "./client";
import type {
AnalyticsAggregatedData,
  AnalyticsFullData, AnalyticsSeriesData, AnalyticsSummaryData, AnalyticsToolBreakdownData,   AnalyticsToolUsageData, BudgetInfo, CostBudgetCreateResult, CostCheckResult,   CostSummary, CostUsageRecord,
PricingInfo, ProjectMetrics,
} from "./types";

export const analyticsApi = {
  analyticsOverview: () => request<AnalyticsFullData["last_hour"] & AnalyticsFullData["last_24h"]>("/api/analytics/overview"),
  analyticsMetrics: () => request<{ metrics: string[] }>("/api/analytics/metrics"),
  analyticsSeries: (metricName: string, since?: number, bucket = "5m") =>
    request<AnalyticsSeriesData>(`/api/analytics/series/${encodeURIComponent(metricName)}?bucket=${bucket}${since ? `&since=${since}` : ""}`),
  analyticsSummary: (since?: number) =>
    request<AnalyticsSummaryData>(`/api/analytics/summary${since ? `?since=${since}` : ""}`),
  analyticsAggregated: (since?: number) =>
    request<AnalyticsAggregatedData>(`/api/analytics/aggregated${since ? `?since=${since}` : ""}`),
  analyticsToolUsage: (since?: number) =>
    request<AnalyticsToolUsageData>(`/api/analytics/tools/usage${since ? `?since=${since}` : ""}`),
  analyticsToolBreakdown: (since?: number) =>
    request<AnalyticsToolBreakdownData>(`/api/analytics/tools/breakdown${since ? `?since=${since}` : ""}`),
  analyticsFull: () => request<AnalyticsFullData>("/api/analytics/full"),
  projectMetrics: () => request<ProjectMetrics>("/api/metrics/project"),
  costUsage: (model: string, inputTokens: number, outputTokens: number, userId = "", channel = "", sessionId = "") =>
    request<{ ok: boolean; cost: number }>("/api/cost/usage", {
      method: "POST", body: JSON.stringify({ model, input_tokens: inputTokens, output_tokens: outputTokens, user_id: userId, channel, session_id: sessionId }),
    }),
  costSummary: (hours = 24) => request<CostSummary>(`/api/cost/summary?hours=${hours}`),
  costPricing: () => request<{ pricing: Record<string, PricingInfo> }>("/api/cost/pricing"),
  costSetPricing: (model: string, inputPer1k: number, outputPer1k: number) =>
    request<{ ok: boolean }>(`/api/cost/pricing/${encodeURIComponent(model)}`, {
      method: "PUT", body: JSON.stringify({ input_per_1k: inputPer1k, output_per_1k: outputPer1k }),
    }),
  costCreateBudget: (name: string, dailyLimit: number, monthlyLimit: number) =>
    request<CostBudgetCreateResult>("/api/cost/budgets", { method: "POST", body: JSON.stringify({ name, daily_limit: dailyLimit, monthly_limit: monthlyLimit }) }),
  costBudgets: () => request<{ budgets: BudgetInfo[] }>("/api/cost/budgets"),
  costDeleteBudget: (id: string) => request<{ ok: boolean }>(`/api/cost/budgets/${id}`, { method: "DELETE" }),
  costCheck: () => request<CostCheckResult>("/api/cost/check"),
  costRecentUsage: (limit = 50) => request<{ usage: CostUsageRecord[] }>(`/api/cost/usage/recent?limit=${limit}`),
};
