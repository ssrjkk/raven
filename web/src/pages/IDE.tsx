import Editor from "@monaco-editor/react"
import { Bot,Bug } from "lucide-react"
import { useCallback,useRef, useState } from "react"

import { api } from "../api/client"
import DebugPanel from "../components/DebugPanel"

interface TerminalLine {
  input: string
  output: string
}

type AgentMode = "build" | "plan" | "general"
type WorkspaceFile = { name: string; path: string; language: string }

const AGENT_MODES: { value: AgentMode; label: string; desc: string }[] = [
  { value: "build",  label: "Build",  desc: "Write & edit code directly" },
  { value: "plan",   label: "Plan",   desc: "Design & architect only (no writes)" },
  { value: "general",label: "General",desc: "Answer questions about code" },
]

export default function IDEPage() {
  const [code, setCode] = useState(`export default function App() {\n  return <h1>Hello Raven</h1>\n}`)
  const [output, setOutput] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  const [agentMode, setAgentMode] = useState<AgentMode>("build")
  const [terminalInput, setTerminalInput] = useState("")
  const [terminalHistory, setTerminalHistory] = useState<TerminalLine[]>([])
  const [workspaceFiles] = useState<WorkspaceFile[]>([])
  const [indexStatus, setIndexStatus] = useState<string>("")
  const [sidebarTab, setSidebarTab] = useState<"ai" | "debug">("ai")
  const terminalEndRef = useRef<HTMLDivElement>(null)

  const scrollTerminal = useCallback(() => {
    setTimeout(() => terminalEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }, [])

  async function runAI() {
    setOutput("Thinking...")
    try {
      const data = await api.ideAgentRun(aiPrompt, agentMode, ".")
      setOutput(data.response || JSON.stringify(data))
    } catch (e) {
      console.error("Agent run failed:", e);
      setOutput("Agent service unavailable. Start with: raven services code-service")
    }
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

  async function searchCodebase() {
    if (!aiPrompt.trim()) return
    setOutput("Searching...")
    try {
      const data = await api.ideContextSearch(aiPrompt, 5)
      const results = data.results || []
      setOutput(results.map(r => `[${r.score.toFixed(2)}] ${r.file}\n${r.content.slice(0, 200)}`).join("\n\n"))
    } catch (e) {
      console.error("Search failed:", e);
      setOutput("Search failed")
    }
  }

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

  return (
    <div className="grid grid-cols-[1fr_320px] h-[calc(100vh-2rem)] bg-[#1e1e1e]">
      <div className="flex flex-col">
        <div className="flex-1 flex flex-col">
          <div className="border-b border-[#333] px-4 py-2 text-xs text-gray-500 bg-[#252526]">
            ssrjkk/workspace/src/app.tsx
          </div>
          <Editor
            height="100%"
            defaultLanguage="typescript"
            theme="vs-dark"
            value={code}
            onChange={(val) => setCode(val ?? "")}
            options={{ minimap: { enabled: false }, fontSize: 14, padding: { top: 16 } }}
          />
        </div>
        <div className="h-60 border-t border-[#333] bg-[#0d0d0d] flex flex-col">
          <div className="px-3 py-1 text-xs text-gray-500 border-b border-[#222] bg-[#252526]">
            Terminal
          </div>
          <div className="flex-1 overflow-auto p-1">
            {terminalHistory.map((line, i) => (
              <div key={i} className="font-mono text-xs text-green-500 px-2 py-0.5 whitespace-pre-wrap">
                <span className="text-gray-500">raven@ssrjkk:~$ </span>{line.input}<br />
                <span className="text-gray-400">{line.output}</span>
              </div>
            ))}
            <div ref={terminalEndRef} />
          </div>
          <div className="flex gap-1 px-2 py-1 border-t border-[#222]">
            <input
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTerminal()}
              placeholder="command..."
              className="flex-1 bg-[#1a1a1a] border border-[#333] rounded px-2.5 py-1.5 text-green-500 text-xs outline-none font-mono"
            />
            <button onClick={runTerminal}
              className="bg-gray-700 hover:bg-gray-600 text-white border-none rounded px-3 py-1.5 cursor-pointer text-xs font-medium transition">
              Run
            </button>
          </div>
        </div>
      </div>

      <div className="border-l border-[#333] flex flex-col bg-[#0d0d0d]">
        <div className="flex border-b border-[#333]">
          <button onClick={() => setSidebarTab("ai")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "ai" ? "bg-[#1e1e1e] text-gray-100" : "bg-transparent text-gray-500 hover:text-gray-300"
            }`}>
            <Bot className="w-3.5 h-3.5" /> AI
          </button>
          <button onClick={() => setSidebarTab("debug")}
            className={`flex items-center gap-1.5 flex-1 px-3 py-2 border-none cursor-pointer text-xs font-medium transition ${
              sidebarTab === "debug" ? "bg-[#1e1e1e] text-gray-100" : "bg-transparent text-gray-500 hover:text-gray-300"
            }`}>
            <Bug className="w-3.5 h-3.5" /> Debug
          </button>
        </div>

        {sidebarTab === "ai" ? (
          <>
            <div className="p-3 border-b border-[#333] flex flex-col gap-2">
              <div className="text-sm font-semibold">AI Agent</div>
              <div className="flex gap-1">
                {AGENT_MODES.map(m => (
                  <button key={m.value} onClick={() => setAgentMode(m.value)}
                    className={`text-xs px-2.5 py-1 rounded border-none cursor-pointer transition ${
                      agentMode === m.value
                        ? "bg-white text-black font-semibold"
                        : "bg-[#333] text-gray-300 hover:bg-[#444]"
                    }`}
                    title={m.desc}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="text-[10px] text-gray-500">{AGENT_MODES.find(m => m.value === agentMode)?.desc}</div>
            </div>

            <div className="flex-1 p-3 overflow-auto flex flex-col gap-3">
              {output && (
                <div className="bg-[#1a1a2e] rounded-lg p-3 text-sm leading-relaxed text-gray-300 whitespace-pre-wrap">
                  {output}
                </div>
              )}
              {workspaceFiles.length > 0 && (
                <div>
                  <div className="text-xs text-gray-500 mb-1 uppercase tracking-wider">Workspace</div>
                  <div className="flex flex-wrap gap-1">
                    {workspaceFiles.map(f => (
                      <span key={f.path} className="text-[10px] bg-[#1e1e1e] px-2 py-0.5 rounded text-gray-400">
                        {f.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {indexStatus && (
                <div className="text-xs text-gray-500">{indexStatus}</div>
              )}
            </div>

            <div className="p-3 border-t border-[#333] flex flex-col gap-2">
              <div className="flex gap-2">
                <input
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder="Ask AI to build anything..."
                  className="flex-1 bg-[#1e1e1e] border border-[#333] rounded-lg px-3 py-2 text-gray-100 text-sm outline-none"
                  onKeyDown={(e) => e.key === "Enter" && (agentMode === "general" ? searchCodebase() : runAI())}
                />
                <button onClick={() => agentMode === "general" ? searchCodebase() : runAI()}
                  className="bg-white hover:bg-gray-200 text-black border-none rounded-lg px-4 py-2 font-semibold cursor-pointer text-sm transition">
                  {agentMode === "general" ? "Search" : "Run"}
                </button>
              </div>
              <div className="flex gap-1">
                <button onClick={indexCodebase}
                  className="bg-[#2a2a2a] hover:bg-[#3a3a3a] text-gray-300 border border-[#444] rounded px-2 py-1 text-[10px] cursor-pointer transition">
                  Index
                </button>
              </div>
            </div>
          </>
        ) : (
          <DebugPanel />
        )}
      </div>
    </div>
  )
}