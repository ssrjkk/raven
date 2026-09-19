import Editor from "@monaco-editor/react"
import { Bot, Bug, Loader2, ShieldAlert } from "lucide-react"
import { useCallback, useRef, useState } from "react"

import { api } from "../api/client"
import DebugPanel from "../components/DebugPanel"
import { useTheme } from "../design/ThemeContext"
import { type AgentSocketEvent, useAgentSocket } from "../hooks/useAgentSocket"

interface TerminalLine {
  input: string
  output: string
}

interface TraceRow {
  id: number
  kind: string
  text: string
}

type AgentMode = "build" | "plan" | "general"
type WorkspaceFile = { name: string; path: string; language: string }

const AGENT_MODES: { value: AgentMode; label: string; desc: string }[] = [
  { value: "build",  label: "Build",  desc: "Write & edit code directly" },
  { value: "plan",   label: "Plan",   desc: "Design & architect only (no writes)" },
  { value: "general",label: "General",desc: "Answer questions about code" },
]

const TRUTHFUL_STATUS: Record<string, { label: string; color: string }> = {
  success: { label: "Verified", color: "badge badge-success" },
  corrected: { label: "Self-corrected", color: "badge badge-warning" },
  refused: { label: "Refused (no data)", color: "badge badge-error" },
}

const AGENT_MODE_TOOLS: Record<AgentMode, { maxSteps: number; diffPreview: boolean }> = {
  build:   { maxSteps: 40, diffPreview: true },
  plan:    { maxSteps: 40, diffPreview: true },
  general: { maxSteps: 30, diffPreview: true },
}

export default function IDEPage() {
  const { theme } = useTheme();
  const [code, setCode] = useState(`export default function App() {\n  return <h1>Hello Raven</h1>\n}`)
  const [output, setOutput] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  const [agentMode, setAgentMode] = useState<AgentMode>("build")
  const [terminalInput, setTerminalInput] = useState("")
  const [terminalHistory, setTerminalHistory] = useState<TerminalLine[]>([])
  const [workspaceFiles] = useState<WorkspaceFile[]>([])
  const [indexStatus, setIndexStatus] = useState<string>("")
  const [sidebarTab, setSidebarTab] = useState<"ai" | "debug">("ai")
  const [truthfulMode, setTruthfulMode] = useState(false)
  const [truthfulStatus, setTruthfulStatus] = useState<string>("")
  const [thinkingProcess, setThinkingProcess] = useState("")
  const [traces, setTraces] = useState<TraceRow[]>([])
  const [pendingConfirm, setPendingConfirm] = useState<{ tool: string; arguments: Record<string, unknown> } | null>(null)
  const streamRef = useRef("")
  const traceIdRef = useRef(0)
  const terminalEndRef = useRef<HTMLDivElement>(null)

  const onAgentEvent = useCallback((ev: AgentSocketEvent) => {
    const d = ev.data as Record<string, unknown>
    if (ev.type === "token") {
      streamRef.current += String(d.content ?? "")
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "final") {
      const content = String(d.content ?? "")
      streamRef.current = content
      setOutput(content)
      return
    }
    if (ev.type === "error") {
      streamRef.current += `\n[error: ${String(d.message ?? "unknown")}]`
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "confirm_request") {
      setPendingConfirm({
        tool: String(d.tool ?? "tool"),
        arguments: (d.arguments ?? {}) as Record<string, unknown>,
      })
      return
    }
    if (ev.type === "done") {
      streamRef.current += `\n\n[done in ${String(d.steps ?? "?")} steps: ${String(d.reason ?? "finished")}]`
      setOutput(streamRef.current)
      return
    }
    if (ev.type === "step_start") {
      traceIdRef.current += 1
      setTraces((prev) => [...prev, { id: traceIdRef.current, kind: "step", text: `Step ${String(d.step ?? "")} — ${String(d.goal ?? "")}` }])
      return
    }
    if (ev.type === "tool_call") {
      let args
      try {
        args = JSON.stringify(d.args)
      } catch {
        args = String(d.args)
      }
      traceIdRef.current += 1
      setTraces((prev) => [...prev, { id: traceIdRef.current, kind: "tool_call", text: `${String(d.name ?? "tool")}(${args})` }])
    }
  }, [])

  const { connected, running, send, respond } = useAgentSocket(onAgentEvent)

  const runAgent = useCallback(() => {
    const prompt = aiPrompt.trim()
    if (!prompt) return
    streamRef.current = ""
    setOutput("")
    setTraces([])
    setTruthfulStatus("")
    setThinkingProcess("")
    const cfg = AGENT_MODE_TOOLS[agentMode]
    send(prompt, { maxSteps: cfg.maxSteps, diffPreview: cfg.diffPreview, proactiveScan: true })
  }, [aiPrompt, agentMode, send])

  async function runAI() {
    if (truthfulMode) {
      setOutput("Thinking...")
      setTruthfulStatus("")
      setThinkingProcess("")
      try {
        const data = await api.truthfulAgent(aiPrompt, code, "general")
        setOutput(data.content)
        setTruthfulStatus(data.status)
        setThinkingProcess(data.thinking_process)
      } catch (e) {
        console.error("Truthful agent failed:", e);
        setOutput("Truthful agent unavailable. Start with: raven services code-service")
      }
      return
    }
    if (agentMode === "general") {
      setOutput("Searching...")
      setTraces([])
      try {
        const data = await api.ideContextSearch(aiPrompt, 5)
        const results = data.results || []
        streamRef.current = results.map(r => `[${r.score.toFixed(2)}] ${r.file}\n${r.content.slice(0, 200)}`).join("\n\n")
        setOutput(streamRef.current)
      } catch (e) {
        console.error("Search failed:", e);
        setOutput("Search failed")
      }
      return
    }
    runAgent()
  }

  async function indexCodebase() {
    setIndexStatus("Indexing...")
    try {
      const data = await api.ideContextIndex(".")
      setIndexStatus(`Indexed ${data.indexed} files`)
    } catch (e) {
      console.error("Indexing failed:", e);
      setIndexStatus("Indexing failed")
    }
  }

  function submitPrompt() {
    runAI()
  }

  const approveConfirm = useCallback(() => {
    if (pendingConfirm) {
      respond({ type: "confirm", data: { approved: true } })
      setPendingConfirm(null)
    }
  }, [pendingConfirm, respond])

  const denyConfirm = useCallback(() => {
    if (pendingConfirm) {
      respond({ type: "confirm", data: { approved: false } })
      setPendingConfirm(null)
    }
  }, [pendingConfirm, respond])

  async function runTerminal() {
    if (!terminalInput.trim()) return
    const cmd = terminalInput.trim()
    setTerminalInput("")
    setTerminalHistory(h => [...h, { input: cmd, output: "Processing..." }])
    scrollTerminal()
    try {
      const data = await api.ideAgentExecute(cmd, "ide-terminal")
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: data.output || data.error || JSON.stringify(data) }
        return copy
      })
    } catch (e) {
      console.error("Terminal exec failed:", e);
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: "[agent unavailable]" }
        return copy
      })
    }
    scrollTerminal()
  }

  const scrollTerminal = useCallback(() => {
    setTimeout(() => terminalEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }, [])

  const busy = running || !connected

  return (
    <div className="grid grid-cols-[1fr_320px] h-[calc(100vh-2rem)] bg-primary">
      <div className="flex flex-col">
        <div className="flex-1 flex flex-col">
          <div className="border-b border-default px-4 py-2 text-xs text-tertiary bg-tertiary">
            ssrjkk/workspace/src/app.tsx
          </div>
          <Editor
            height="100%"
            defaultLanguage="typescript"
            theme={theme === "dark" ? "vs-dark" : "light"}
            value={code}
            onChange={(val) => setCode(val ?? "")}
            options={{ minimap: { enabled: false }, fontSize: 14, padding: { top: 16 } }}
          />
        </div>
        <div className="h-60 border-t border-default bg-secondary flex flex-col">
          <div className="px-3 py-1 text-xs text-tertiary border-b border-default bg-tertiary">
            Terminal
          </div>
          <div className="flex-1 overflow-auto p-1">
            {terminalHistory.map((line, i) => (
              <div key={i} className="font-mono text-xs text-success px-2 py-0.5 whitespace-pre-wrap">
                <span className="text-tertiary">raven@ssrjkk:~$ </span>{line.input}<br />
                <span className="text-tertiary">{line.output}</span>
              </div>
            ))}
            <div ref={terminalEndRef} />
          </div>
          <div className="flex gap-1 px-2 py-1 border-t border-default">
            <input
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTerminal()}
              placeholder="command..."
              className="flex-1 input-base font-mono text-xs"
            />
            <button onClick={runTerminal}
              className="btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
              Run
            </button>
          </div>
        </div>
      </div>

      <div className="border-l border-default flex flex-col bg-secondary relative">
        <div className="flex border-b border-default">
          <button onClick={() => setSidebarTab("ai")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "ai" ? "bg-primary text-primary" : "bg-transparent text-tertiary hover:text-secondary"
            }`}>
            <Bot className="w-3.5 h-3.5" /> AI
          </button>
          <button onClick={() => setSidebarTab("debug")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "debug" ? "bg-primary text-primary" : "bg-transparent text-tertiary hover:text-secondary"
            }`}>
            <Bug className="w-3.5 h-3.5" /> Debug
          </button>
        </div>

        {sidebarTab === "ai" ? (
          <>
            <div className="p-3 border-b border-default flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">AI Agent</div>
                <div className="flex items-center gap-1.5 text-[10px] text-tertiary">
                  <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`} />
                  {connected ? (running ? "working" : "idle") : "offline"}
                </div>
              </div>
              <div className="flex gap-1">
                {AGENT_MODES.map(m => (
                  <button key={m.value} onClick={() => setAgentMode(m.value)} disabled={running}
                    className={`text-xs px-2.5 py-1 rounded border-none cursor-pointer transition ${
                      agentMode === m.value
                        ? "bg-accent text-white font-semibold"
                        : "bg-tertiary text-secondary hover:bg-accent-muted"
                    } ${running ? "opacity-50" : ""}`}
                    title={m.desc}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="text-[10px] text-tertiary">{AGENT_MODES.find(m => m.value === agentMode)?.desc}</div>
              <button onClick={() => setTruthfulMode(v => !v)}
                className={`flex items-center justify-center gap-1.5 text-xs px-2.5 py-1.5 rounded border-none cursor-pointer transition ${
                  truthfulMode
                    ? "bg-accent-muted text-accent font-semibold"
                    : "bg-tertiary text-tertiary hover:bg-accent-muted"
                }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${truthfulMode ? "bg-accent" : "bg-tertiary"}`} />
                Truthful mode (Chain-of-Verification)
              </button>
            </div>

            <div className="flex-1 p-3 overflow-auto flex flex-col gap-3">
              {truthfulStatus && (
                <div className="flex items-center gap-2">
                  <span className={TRUTHFUL_STATUS[truthfulStatus]?.color ?? "badge badge-accent"}>
                    {TRUTHFUL_STATUS[truthfulStatus]?.label ?? truthfulStatus}
                  </span>
                </div>
              )}
              {output && (
                <div className="card p-3 text-sm leading-relaxed text-secondary whitespace-pre-wrap">
                  {output}
                </div>
              )}
              {traces.length > 0 && (
                <div className="card p-3 flex flex-col gap-1.5">
                  <div className="text-[10px] text-accent uppercase tracking-wider">Agent trace</div>
                  {traces.map(t => (
                    <div key={t.id} className={`font-mono text-xs whitespace-pre-wrap ${t.kind === "tool_call" ? "text-accent" : "text-tertiary"}`}>
                      {t.text}
                    </div>
                  ))}
                </div>
              )}
              {running && (
                <div className="flex items-center gap-2 text-sm text-secondary">
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                  Agent is working…
                </div>
              )}
              {thinkingProcess && (
                <details className="card p-3">
                  <summary className="text-[10px] text-accent cursor-pointer uppercase tracking-wider">
                    Verification thinking
                  </summary>
                  <pre className="text-xs text-tertiary whitespace-pre-wrap mt-2 font-mono">{thinkingProcess}</pre>
                </details>
              )}
              {workspaceFiles.length > 0 && (
                <div>
                  <div className="text-xs text-tertiary mb-1 uppercase tracking-wider">Workspace</div>
                  <div className="flex flex-wrap gap-1">
                    {workspaceFiles.map(f => (
                      <span key={f.path} className="chip">
                        {f.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {indexStatus && (
                <div className="text-xs text-tertiary">{indexStatus}</div>
              )}
            </div>

            <div className="p-3 border-t border-default flex flex-col gap-2">
              <div className="flex gap-2">
                <input
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder="Ask AI to build anything..."
                  className="flex-1 input-base"
                  onKeyDown={(e) => e.key === "Enter" && submitPrompt()}
                  disabled={running}
                />
                <button onClick={submitPrompt} disabled={busy}
                  className="btn-primary">
                  {running ? "Working..." : truthfulMode ? "Verify" : agentMode === "general" ? "Search" : "Run"}
                </button>
              </div>
              <div className="flex gap-1">
                <button onClick={indexCodebase}
                  className="btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
                  Index
                </button>
              </div>
            </div>
          </>
        ) : (
          <DebugPanel />
        )}

        {pendingConfirm && (
          <div className="absolute inset-0 z-20 bg-black/50 flex items-center justify-center p-4">
            <div className="card p-4 w-full max-w-xs bg-tertiary">
              <div className="flex items-center gap-2 text-sm font-semibold text-primary mb-2">
                <ShieldAlert className="h-4 w-4 text-amber-400" />
                Allow tool?
              </div>
              <div className="text-xs text-secondary mb-1">The agent wants to run:</div>
              <div className="font-mono text-xs text-accent mb-3 bg-primary rounded px-2 py-1.5 break-all">
                {pendingConfirm.tool}
              </div>
              <div className="font-mono text-[10px] text-tertiary mb-4 bg-primary rounded px-2 py-1.5 whitespace-pre-wrap max-h-28 overflow-auto">
                {JSON.stringify(pendingConfirm.arguments, null, 2)}
              </div>
              <div className="flex gap-2">
                <button onClick={denyConfirm}
                  className="btn-outline flex-1">
                  Deny
                </button>
                <button onClick={approveConfirm}
                  className="btn-primary flex-1">
                  Allow
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}