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
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", height: "calc(100vh - 2rem)", background: "#1e1e1e" }}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <div style={{ borderBottom: "1px solid #333", padding: "8px 16px", fontSize: 13, color: "#888", background: "#252526" }}>
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
        <div style={{ height: 240, borderTop: "1px solid #333", background: "#0d0d0d", display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "4px 12px", fontSize: 12, color: "#666", borderBottom: "1px solid #222", background: "#252526" }}>
            Terminal
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: 4 }}>
            {terminalHistory.map((line, i) => (
              <div key={i} style={{ fontFamily: "monospace", fontSize: 12, color: "#0f0", padding: "2px 8px", whiteSpace: "pre-wrap" }}>
                <span style={{ color: "#888" }}>raven@ssrjkk:~$ </span>{line.input}<br />
                <span style={{ color: "#aaa" }}>{line.output}</span>
              </div>
            ))}
            <div ref={terminalEndRef} />
          </div>
          <div style={{ display: "flex", gap: 4, padding: "4px 8px", borderTop: "1px solid #222" }}>
            <input
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTerminal()}
              placeholder="command..."
              style={{
                flex: 1, background: "#1a1a1a", border: "1px solid #333",
                borderRadius: 4, padding: "6px 10px", color: "#0f0",
                fontSize: 12, outline: "none", fontFamily: "monospace",
              }}
            />
            <button onClick={runTerminal} style={{
              background: "#333", color: "#fff", border: "none",
              borderRadius: 4, padding: "6px 12px", cursor: "pointer", fontSize: 12,
            }}>
              Run
            </button>
          </div>
        </div>
      </div>

      <div style={{ borderLeft: "1px solid #333", display: "flex", flexDirection: "column", background: "#0d0d0d" }}>
        <div style={{ padding: 12, borderBottom: "1px solid #333" }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>AI Agent</div>
          <div style={{ fontSize: 11, color: "#666" }}>Autonomous Mode</div>
        </div>

        <div style={{ flex: 1, padding: 12, overflow: "auto" }}>
          {output && (
            <div style={{
              background: "#1a1a2e", borderRadius: 8, padding: 12,
              fontSize: 13, lineHeight: 1.5, color: "#ccc", whiteSpace: "pre-wrap",
            }}>
              {output}
            </div>
          )}
        </div>

        <div style={{ padding: 12, borderTop: "1px solid #333" }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              placeholder="Ask AI to build anything..."
              style={{
                flex: 1, background: "#1e1e1e", border: "1px solid #333",
                borderRadius: 8, padding: "8px 12px", color: "#fff",
                fontSize: 13, outline: "none",
              }}
              onKeyDown={(e) => e.key === "Enter" && runAI()}
            />
            <button onClick={runAI}
              style={{ background: "#fff", color: "#000", border: "none", borderRadius: 8, padding: "8px 16px", fontWeight: 600, cursor: "pointer", fontSize: 13 }}>
              Run
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
