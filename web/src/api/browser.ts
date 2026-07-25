import { request } from "./client";
import type {
BrowserActionResult, BrowserEvaluateResult,
  BrowserExtractResult, BrowserScreenshotResult,   BrowserStatusData, BrowserTabInfo, BrowserTitleResult, BrowserUrlResult,
BrowserVisualDiffResult, } from "./types";

export const browserApi = {
  browserStatus: () => request<BrowserStatusData>("/api/browser/status"),
  browserStart: () => request<BrowserActionResult>("/api/browser/start", { method: "POST" }),
  browserStop: () => request<BrowserActionResult>("/api/browser/stop", { method: "POST" }),
  browserNavigate: (url: string, waitUntil = "domcontentloaded", timeout = 30) =>
    request<BrowserActionResult>("/api/browser/navigate", { method: "POST", body: JSON.stringify({ url, wait_until: waitUntil, timeout }) }),
  browserClick: (selector: string, timeout = 10) =>
    request<BrowserActionResult>("/api/browser/click", { method: "POST", body: JSON.stringify({ selector, timeout }) }),
  browserFill: (selector: string, value: string, timeout = 10) =>
    request<BrowserActionResult>("/api/browser/fill", { method: "POST", body: JSON.stringify({ selector, value, timeout }) }),
  browserScreenshot: (selector?: string, fullPage = false) =>
    request<BrowserScreenshotResult>("/api/browser/screenshot", { method: "POST", body: JSON.stringify({ selector, full_page: fullPage }) }),
  browserEvaluate: (script: string) =>
    request<BrowserEvaluateResult>("/api/browser/evaluate", { method: "POST", body: JSON.stringify({ script }) }),
  browserExtract: (url?: string) =>
    request<BrowserExtractResult>("/api/browser/extract", { method: "POST", body: JSON.stringify({ url }) }),
  browserVisualDiff: (urlA: string, urlB: string, fullPage = false) =>
    request<BrowserVisualDiffResult>("/api/browser/visual-diff", { method: "POST", body: JSON.stringify({ url_a: urlA, url_b: urlB, full_page: fullPage }) }),
  browserTabList: () => request<BrowserTabInfo[]>("/api/browser/tabs"),
  browserTabNew: (url?: string) =>
    request<BrowserTabInfo>("/api/browser/tabs", { method: "POST", body: JSON.stringify({ url }) }),
  browserTitle: () => request<BrowserTitleResult>("/api/browser/title"),
  browserUrl: () => request<BrowserUrlResult>("/api/browser/url"),
};
