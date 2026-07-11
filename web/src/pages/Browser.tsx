import { useState } from "react";
import { request } from "../api/client";

type Tab = "navigate" | "interact" | "tabs" | "network" | "extract";

export default function Browser() {
  const [tab, setTab] = useState<Tab>("navigate");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [agentStatus, setAgentStatus] = useState<any>(null);

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

  async function checkStatus() {
    setLoading(true); setError("");
    try {
      const r = await request<any>("/api/browser/status");
      setAgentStatus(r);
      setOutput(r.started ? `Browser started — ${r.title || ""} ${r.url || ""}` : "Browser not started");
    } catch (e: any) {
      setError(e.message || "Status failed");
    } finally { setLoading(false); }
  }

  async function startAgent() {
    setLoading(true); setError(""); setOutput("");
    try {
      const r = await request<any>("/api/browser/start", { method: "POST" });
      setOutput(`Browser agent ${r.status}`);
      checkStatus();
    } catch (e: any) {
      setError(e.message || "Start failed");
    } finally { setLoading(false); }
  }

  async function doAction(action: string, body?: any) {
    setLoading(true); setError(""); setOutput("");
    try {
      const r = await request<any>(`/api/browser/${action}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      setOutput(typeof r.result === "string" ? r.result : JSON.stringify(r, null, 2));
    } catch (e: any) {
      setError(e.message || `${action} failed`);
    } finally { setLoading(false); }
  }

  async function doExtract() {
    setLoading(true); setError(""); setOutput("");
    try {
      const r = await request<any>("/api/browser/extract", { method: "POST", body: JSON.stringify({ url: extractUrl || undefined }) });
      setOutput(r.content || "No content extracted");
    } catch (e: any) {
      setError(e.message || "Extract failed");
    } finally { setLoading(false); }
  }

  async function doVisualDiff() {
    setLoading(true); setError(""); setOutput("");
    try {
      const r = await request<any>("/api/browser/visual-diff", { method: "POST", body: JSON.stringify({ url_a: diffUrlA, url_b: diffUrlB }) });
      setOutput(JSON.stringify({ diff_percent: r.diff_percent, url_a: r.url_a, url_b: r.url_b }, null, 2));
    } catch (e: any) {
      setError(e.message || "Visual diff failed");
    } finally { setLoading(false); }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Browser Automation</h1>

      <div className="flex flex-wrap gap-2 mb-4">
        <button onClick={startAgent} disabled={loading}
          className="px-3 py-1.5 rounded-lg text-sm font-medium" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
          {loading ? "..." : "Start Browser"}
        </button>
        <button onClick={checkStatus} disabled={loading}
          className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
          Status
        </button>
        <button onClick={() => doAction("stop")} disabled={loading}
          className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
          Stop
        </button>
      </div>

      {agentStatus?.started && (
        <div className="p-2 mb-4 rounded-lg text-xs" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>
          Running — {agentStatus.title || "no page"} ({agentStatus.url || "no url"})
        </div>
      )}

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}

      <div className="flex gap-1 mb-4 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["navigate", "interact", "tabs", "network", "extract"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className="px-3 py-1.5 text-sm font-medium rounded-t-lg transition capitalize"
            style={{ color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t}
          </button>
        ))}
      </div>

      {tab === "navigate" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Navigate</h2>
            <div className="flex gap-2 mb-3">
              <input value={navUrl} onChange={e => setNavUrl(e.target.value)} placeholder="https://example.com"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("navigate", { url: navUrl })} disabled={loading || !navUrl}
                className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Go
              </button>
            </div>
            <div className="flex gap-2">
              <input value={ssUrl} onChange={e => setSsUrl(e.target.value)} placeholder="URL for screenshot"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("screenshot", { selector: null, full_page: false })} disabled={loading || !ssUrl}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
                Screenshot
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Info</h2>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => doAction("title")} disabled={loading} className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>Get Title</button>
              <button onClick={() => doAction("url")} disabled={loading} className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>Get URL</button>
              <button onClick={() => doAction("text", { selector: "body" })} disabled={loading} className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>Get Text</button>
            </div>
          </div>
        </div>
      )}

      {tab === "interact" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Click</h2>
            <div className="flex gap-2">
              <input value={clickSel} onChange={e => setClickSel(e.target.value)} placeholder="CSS selector"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("click", { selector: clickSel })} disabled={loading || !clickSel}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Click
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Fill Input</h2>
            <div className="flex gap-2 mb-2">
              <input value={fillSel} onChange={e => setFillSel(e.target.value)} placeholder="CSS selector"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <input value={fillVal} onChange={e => setFillVal(e.target.value)} placeholder="Value"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("fill", { selector: fillSel, value: fillVal })} disabled={loading || !fillSel}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Fill
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Evaluate JS</h2>
            <div className="flex gap-2">
              <input value={evalScript} onChange={e => setEvalScript(e.target.value)} placeholder="document.title"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("evaluate", { script: evalScript })} disabled={loading || !evalScript}
                className="px-4 py-2 rounded-lg text-sm disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Run
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Scroll</h2>
            <div className="flex gap-2">
              <select value={scrollDir} onChange={e => setScrollDir(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}>
                <option value="down">Down</option>
                <option value="up">Up</option>
              </select>
              <input value={scrollAmt} onChange={e => setScrollAmt(e.target.value)} placeholder="pixels" type="number"
                className="w-24 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("scroll", { direction: scrollDir, amount: parseInt(scrollAmt) || 500 })} disabled={loading}
                className="px-4 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Scroll
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "tabs" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">New Tab</h2>
            <div className="flex gap-2">
              <input value={newTabUrl} onChange={e => setNewTabUrl(e.target.value)} placeholder="URL (optional)"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("new-tab", { url: newTabUrl || null })} disabled={loading}
                className="px-4 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                New Tab
              </button>
            </div>
          </div>

          <div className="flex gap-2">
            <button onClick={() => doAction("list-tabs")} disabled={loading}
              className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
              List Tabs
            </button>
            <div className="flex gap-1 items-center">
              <input value={tabIndex} onChange={e => setTabIndex(e.target.value)} placeholder="index" type="number" className="w-16 px-2 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={() => doAction("switch-tab", { index: parseInt(tabIndex) || 0 })} disabled={loading}
                className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
                Switch
              </button>
              <button onClick={() => doAction("close-tab", {})} disabled={loading}
                className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "network" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Network Intercept</h2>
            <div className="flex gap-2 mb-3">
              {!interceptActive ? (
                <button onClick={async () => { await doAction("intercept", { action: "start" }); setInterceptActive(true); }} disabled={loading}
                  className="px-4 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                  Start Capture
                </button>
              ) : (
                <button onClick={async () => { await doAction("intercept", { action: "stop" }); setInterceptActive(false); }} disabled={loading}
                  className="px-4 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: "rgba(239,68,68,0.8)", color: "#fff" }}>
                  Stop Capture
                </button>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => doAction("requests")} disabled={loading}
                className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
                Get Requests
              </button>
              <button onClick={() => doAction("responses")} disabled={loading}
                className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
                Get Responses
              </button>
            </div>
          </div>
        </div>
      )}

      {tab === "extract" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Content Extraction</h2>
            <div className="flex gap-2 mb-3">
              <input value={extractUrl} onChange={e => setExtractUrl(e.target.value)} placeholder="URL (optional, uses current page)"
                className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={doExtract} disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Extract
              </button>
            </div>
            <p className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Extracts clean article/main content, removing navigation, ads, sidebars, and comments.</p>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Visual Diff</h2>
            <div className="space-y-2">
              <input value={diffUrlA} onChange={e => setDiffUrlA(e.target.value)} placeholder="URL A (first page)"
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <input value={diffUrlB} onChange={e => setDiffUrlB(e.target.value)} placeholder="URL B (second page)"
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <button onClick={doVisualDiff} disabled={loading || !diffUrlA || !diffUrlB}
                className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Compare
              </button>
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--dt-colors-text-tertiary)" }}>Computes pixel-level difference percentage between two page screenshots.</p>
          </div>
        </div>
      )}

      {output && (
        <div className="p-4 mt-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--dt-colors-text-secondary)" }}>Output</h2>
          <pre className="text-xs whitespace-pre-wrap overflow-auto max-h-80" style={{ color: "var(--dt-colors-text-primary)" }}>
            {output}
          </pre>
        </div>
      )}
    </div>
  );
}
