import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, type BrowserStatusData } from "../api/client";

type Tab = "navigate" | "interact" | "tabs" | "network" | "extract";

export default function Browser() {
  const [tab, setTab] = useState<Tab>("navigate");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [agentStatus, setAgentStatus] = useState<BrowserStatusData | null>(null);

  // navigate
  const [navUrl, setNavUrl] = useState("");
  const [ssUrl, setSsUrl] = useState("");

  // click
  const [clickSel, setClickSel] = useState("");
  const [fillSel, setFillSel] = useState("");
  const [fillVal, setFillVal] = useState("");
  const [evalScript, setEvalScript] = useState("");
  const [scrollDir, setScrollDir] = useState("down");
  const [scrollAmt, setScrollAmt] = useState("500");

  // tab mgmt
  const [tabIndex, setTabIndex] = useState("0");
  const [newTabUrl, setNewTabUrl] = useState("");
  const [interceptActive, setInterceptActive] = useState(false);

  // extract
  const [extractUrl, setExtractUrl] = useState("");
  const [diffUrlA, setDiffUrlA] = useState("");
  const [diffUrlB, setDiffUrlB] = useState("");

  const statusMutation = useMutation({
    mutationFn: () => api.browserStatus(),
    onSuccess: (r) => {
      setAgentStatus(r);
      setOutput(r.running ? `Browser started РІР‚вЂќ ${r.title || ""} ${r.url || ""}` : "Browser not started");
      setError("");
    },
    onError: (e: any) => setError(e.message || "Status failed"),
  });

  const startMutation = useMutation({
    mutationFn: () => api.browserStart(),
    onSuccess: (r) => {
      setOutput(`Browser agent ${r.message || "started"}`);
      setError("");
      statusMutation.mutate();
    },
    onError: (e: any) => setError(e.message || "Start failed"),
  });

  const actionMutation = useMutation({
    mutationFn: async ({ action, body }: { action: string; body?: Record<string, unknown> }) => {
      switch (action) {
        case "navigate": return await api.browserNavigate((body?.url as string) ?? "", "domcontentloaded", 30);
        case "click": return await api.browserClick((body?.selector as string) ?? "");
        case "fill": return await api.browserFill((body?.selector as string) ?? "", (body?.value as string) ?? "");
        case "evaluate": return await api.browserEvaluate((body?.script as string) ?? "");
        case "screenshot": return await api.browserScreenshot((body?.selector as string | undefined) ?? undefined, (body?.full_page as boolean) ?? false);
        case "title": return await api.browserTitle();
        case "url": return await api.browserUrl();
        case "list-tabs": return await api.browserTabList();
        case "new-tab": return await api.browserTabNew((body?.url as string | undefined) ?? undefined);
        case "extract": return await api.browserExtract(body?.url as string | undefined);
        case "visual-diff": return await api.browserVisualDiff((body?.url_a as string) ?? "", (body?.url_b as string) ?? "");
        case "stop": return await api.browserStop();
        case "text": return await api.browserEvaluate(`document.querySelector(${JSON.stringify(body?.selector ?? "body")}).innerText`);
        case "scroll": {
          const dir = body?.direction === "up" ? -1 : 1;
          return await api.browserEvaluate(`window.scrollBy(0, ${dir * ((body?.amount as number) ?? 500)})`);
        }
        case "switch-tab": return await api.browserTabSwitch(body?.index as number);
        case "close-tab": return await api.browserTabClose();
        case "intercept": return await api.browserIntercept(body?.action as string);
        case "requests": return await api.browserRequests();
        case "responses": return await api.browserResponses();
        default: throw new Error(`Unknown action: ${action}`);
      }
    },
    onSuccess: (result) => {
      setOutput(typeof result === "string" ? result : JSON.stringify(result, null, 2));
      setError("");
    },
    onError: (e: any, { action }) => setError(e.message || `${action} failed`),
  });

  const extractMutation = useMutation({
    mutationFn: () => api.browserExtract(extractUrl || undefined),
    onSuccess: (r) => { setOutput(r.text || "No content extracted"); setError(""); },
    onError: (e: any) => setError(e.message || "Extract failed"),
  });

  const diffMutation = useMutation({
    mutationFn: () => api.browserVisualDiff(diffUrlA, diffUrlB),
    onSuccess: (r) => { setOutput(JSON.stringify({ diff_percent: r.diff_percent }, null, 2)); setError(""); },
    onError: (e: any) => setError(e.message || "Visual diff failed"),
  });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Browser Automation</h1>

      <div className="flex flex-wrap gap-2 mb-4">
        <button onClick={() => startMutation.mutate()} disabled={startMutation.isPending}
          className="px-3 py-1.5 rounded-lg text-sm font-medium bg-accent text-white">
          {startMutation.isPending ? "..." : "Start Browser"}
        </button>
        <button onClick={() => statusMutation.mutate()} disabled={statusMutation.isPending}
          className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
          Status
        </button>
        <button onClick={() => actionMutation.mutate({ action: "stop" })} disabled={actionMutation.isPending}
          className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
          Stop
        </button>
      </div>

      {agentStatus?.running && (
        <div className="p-2 mb-4 rounded-lg text-xs bg-success-muted text-success">
          Running РІР‚вЂќ {agentStatus.title || "no page"} ({agentStatus.url || "no url"})
        </div>
      )}

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}

      <div className="flex gap-1 mb-4 border-b border-default">
        {(["navigate", "interact", "tabs", "network", "extract"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className="px-3 py-1.5 text-sm font-medium rounded-t-lg transition capitalize"
            style={{ color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t}
          </button>
        ))}
      </div>

      {tab === "navigate" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Navigate</h2>
            <div className="flex gap-2 mb-3">
              <input value={navUrl} onChange={e => setNavUrl(e.target.value)} placeholder="https://example.com"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "navigate", body: { url: navUrl } })} disabled={actionMutation.isPending || !navUrl}
                className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 bg-accent text-white">
                Go
              </button>
            </div>
            <div className="flex gap-2">
              <input value={ssUrl} onChange={e => setSsUrl(e.target.value)} placeholder="URL for screenshot"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "screenshot", body: { selector: null, full_page: false } })} disabled={actionMutation.isPending || !ssUrl}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50 btn-tertiary">
                Screenshot
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Info</h2>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => actionMutation.mutate({ action: "title" })} disabled={actionMutation.isPending} className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">Get Title</button>
              <button onClick={() => actionMutation.mutate({ action: "url" })} disabled={actionMutation.isPending} className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">Get URL</button>
              <button onClick={() => actionMutation.mutate({ action: "text", body: { selector: "body" } })} disabled={actionMutation.isPending} className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">Get Text</button>
            </div>
          </div>
        </div>
      )}

      {tab === "interact" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Click</h2>
            <div className="flex gap-2">
              <input value={clickSel} onChange={e => setClickSel(e.target.value)} placeholder="CSS selector"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "click", body: { selector: clickSel } })} disabled={actionMutation.isPending || !clickSel}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50 bg-accent text-white">
                Click
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Fill Input</h2>
            <div className="flex gap-2 mb-2">
              <input value={fillSel} onChange={e => setFillSel(e.target.value)} placeholder="CSS selector"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <input value={fillVal} onChange={e => setFillVal(e.target.value)} placeholder="Value"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "fill", body: { selector: fillSel, value: fillVal } })} disabled={actionMutation.isPending || !fillSel}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50 bg-accent text-white">
                Fill
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Evaluate JS</h2>
            <div className="flex gap-2">
              <input value={evalScript} onChange={e => setEvalScript(e.target.value)} placeholder="document.title"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "evaluate", body: { script: evalScript } })} disabled={actionMutation.isPending || !evalScript}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50 bg-accent text-white">
                Run
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Scroll</h2>
            <div className="flex gap-2">
              <select value={scrollDir} onChange={e => setScrollDir(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default">
                <option value="down">Down</option>
                <option value="up">Up</option>
              </select>
              <input value={scrollAmt} onChange={e => setScrollAmt(e.target.value)} placeholder="pixels" type="number"
                className="w-24 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "scroll", body: { direction: scrollDir, amount: parseInt(scrollAmt) || 500 } })} disabled={actionMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm bg-accent text-white">
                Scroll
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "tabs" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">New Tab</h2>
            <div className="flex gap-2">
              <input value={newTabUrl} onChange={e => setNewTabUrl(e.target.value)} placeholder="URL (optional)"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "new-tab", body: { url: newTabUrl || null } })} disabled={actionMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm bg-accent text-white">
                New Tab
              </button>
            </div>
          </div>

          <div className="flex gap-2">
            <button onClick={() => actionMutation.mutate({ action: "list-tabs" })} disabled={actionMutation.isPending}
              className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
              List Tabs
            </button>
            <div className="flex gap-1 items-center">
              <input value={tabIndex} onChange={e => setTabIndex(e.target.value)} placeholder="index" type="number" className="w-16 px-2 py-1.5 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => actionMutation.mutate({ action: "switch-tab", body: { index: parseInt(tabIndex) || 0 } })} disabled={actionMutation.isPending}
                className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
                Switch
              </button>
              <button onClick={() => actionMutation.mutate({ action: "close-tab" })} disabled={actionMutation.isPending}
                className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "network" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Network Intercept</h2>
            <div className="flex gap-2 mb-3">
              {!interceptActive ? (
                <button onClick={() => { actionMutation.mutate({ action: "intercept", body: { action: "start" } }); setInterceptActive(true); }} disabled={actionMutation.isPending}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white">
                  Start Capture
                </button>
              ) : (
                <button onClick={() => { actionMutation.mutate({ action: "intercept", body: { action: "stop" } }); setInterceptActive(false); }} disabled={actionMutation.isPending}
                  className="px-4 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: "rgba(239,68,68,0.8)", color: "#fff" }}>
                  Stop Capture
                </button>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => actionMutation.mutate({ action: "requests" })} disabled={actionMutation.isPending}
                className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
                Get Requests
              </button>
              <button onClick={() => actionMutation.mutate({ action: "responses" })} disabled={actionMutation.isPending}
                className="px-3 py-1.5 rounded-lg text-sm btn-tertiary">
                Get Responses
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "extract" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Content Extraction</h2>
            <div className="flex gap-2 mb-3">
              <input value={extractUrl} onChange={e => setExtractUrl(e.target.value)} placeholder="URL (optional, uses current page)"
                className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => extractMutation.mutate()} disabled={extractMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white">
                {extractMutation.isPending ? "Extracting..." : "Extract"}
              </button>
            </div>
            <p className="text-xs text-tertiary">Extracts clean article/main content, removing navigation, ads, sidebars, and comments.</p>
          </div>

          <div className="p-4 rounded-lg bg-secondary">
            <h2 className="text-lg font-semibold mb-3">Visual Diff</h2>
            <div className="space-y-2">
              <input value={diffUrlA} onChange={e => setDiffUrlA(e.target.value)} placeholder="URL A (first page)"
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <input value={diffUrlB} onChange={e => setDiffUrlB(e.target.value)} placeholder="URL B (second page)"
                className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
              <button onClick={() => diffMutation.mutate()} disabled={diffMutation.isPending || !diffUrlA || !diffUrlB}
                className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 bg-accent text-white">
                {diffMutation.isPending ? "Comparing..." : "Compare"}
              </button>
            </div>
            <p className="text-xs mt-2 text-tertiary">Computes pixel-level difference percentage between two page screenshots.</p>
          </div>
        </div>
      )}

      {output && (
        <div className="p-4 mt-4 rounded-lg bg-secondary">
          <h2 className="text-sm font-semibold mb-2 text-secondary">Output</h2>
          <pre className="text-xs whitespace-pre-wrap overflow-auto max-h-80 text-primary">
            {output}
          </pre>
        </div>
      )}
    </div>
  );
}
