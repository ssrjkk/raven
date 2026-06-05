import { useState, useRef, useCallback } from "react"
import Editor from "@monaco-editor/react"

interface TerminalLine {
  input: string
  output: string
}

export default function IDEPage() {
  const [code, setCode] = useState(`export default function App() {\n  return <h1>Hello Raven</h1>\n}`)
  const [output, setOutput] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  const [terminalInput, setTerminalInput] = useState("")
  const [terminalHistory, setTerminalHistory] = useState<TerminalLine[]>([])
  const terminalEndRef = useRef<HTMLDivElement>(null)

  const scrollTerminal = useCallback(() => {
    setTimeout(() => terminalEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }, [])

  async function runAI() {
    setOutput("Thinking...")
    try {
      const res = await fetch("/api/aios/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: aiPrompt, task: "code" }),
      })
      const data = await res.json()
      setOutput(data.text || JSON.stringify(data))
    } catch {
      setOutput("AI Gateway unavailable. Start with: raven aios gateway")
    }
  }

  async function runTerminal() {
    if (!terminalInput.trim()) return
    const cmd = terminalInput.trim()
    setTerminalInput("")
    setTerminalHistory(h => [...h, { input: cmd, output: "Executing..." }])
    scrollTerminal()
    try {
      const res = await fetch("/api/aios/exec", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd }),
      })
      const data = await res.json()
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: data.output || data.error || JSON.stringify(data) }
        return copy
      })
    } catch {
      setTerminalHistory(h => {
        const copy = [...h]
        copy[copy.length - 1] = { input: cmd, output: "[executed locally]" }
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
        <div className="p-3 border-b border-[#333]">
          <div className="text-sm font-semibold mb-1">AI Agent</div>
          <div className="text-xs text-gray-500">Autonomous Mode</div>
        </div>

        <div className="flex-1 p-3 overflow-auto">
          {output && (
            <div className="bg-[#1a1a2e] rounded-lg p-3 text-sm leading-relaxed text-gray-300 whitespace-pre-wrap">
              {output}
            </div>
          )}
        </div>

        <div className="p-3 border-t border-[#333]">
          <div className="flex gap-2">
            <input
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              placeholder="Ask AI to build anything..."
              className="flex-1 bg-[#1e1e1e] border border-[#333] rounded-lg px-3 py-2 text-gray-100 text-sm outline-none"
              onKeyDown={(e) => e.key === "Enter" && runAI()}
            />
            <button onClick={runAI}
              className="bg-white hover:bg-gray-200 text-black border-none rounded-lg px-4 py-2 font-semibold cursor-pointer text-sm transition">
              Run
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}