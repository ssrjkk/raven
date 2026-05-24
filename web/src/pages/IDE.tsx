import { useState, useEffect, useRef } from "react"

export default function IDEPage() {
  const [code, setCode] = useState(`export default function App() {\n  return <h1>Hello Raven</h1>\n}`)
  const [output, setOutput] = useState("")
  const [aiPrompt, setAiPrompt] = useState("")
  const [terminalInput, setTerminalInput] = useState("")
  const terminalRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.textContent = "raven@ai-os:~$ "
    }
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
      setOutput(data.text)
    } catch {
      setOutput("AI Gateway unavailable. Start with: raven aios gateway")
    }
  }

  function runTerminal() {
    if (terminalRef.current && terminalInput.trim()) {
      terminalRef.current.textContent += `\nraven@ai-os:~$ ${terminalInput}\n[executed]`
      setTerminalInput("")
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", height: "calc(100vh - 2rem)" }}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <div style={{ borderBottom: "1px solid #333", padding: "8px 16px", fontSize: 13, color: "#888" }}>
            ssrjkk/workspace/src/app.tsx
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            style={{
              flex: 1,
              background: "#1e1e1e",
              color: "#d4d4d4",
              border: "none",
              padding: 16,
              fontFamily: "'Fira Code', 'Cascadia Code', monospace",
              fontSize: 14,
              resize: "none",
              outline: "none",
            }}
            spellCheck={false}
          />
        </div>
        <div style={{ height: 200, borderTop: "1px solid #333", background: "#0d0d0d" }}>
          <div style={{ padding: "4px 12px", fontSize: 12, color: "#666", borderBottom: "1px solid #222" }}>
            Terminal
          </div>
          <div style={{ display: "flex", gap: 4, padding: "4px 8px" }}>
            <input
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runTerminal()}
              placeholder="command..."
              style={{
                flex: 1, background: "#1a1a1a", border: "1px solid #333",
                borderRadius: 4, padding: "4px 8px", color: "#0f0",
                fontSize: 12, outline: "none", fontFamily: "monospace",
              }}
            />
            <button onClick={runTerminal} style={{
              background: "#333", color: "#fff", border: "none",
              borderRadius: 4, padding: "4px 10px", cursor: "pointer", fontSize: 12,
            }}>
              Run
            </button>
          </div>
          <pre
            ref={terminalRef}
            style={{
              margin: 0, padding: "4px 8px", color: "#0f0",
              fontFamily: "monospace", fontSize: 12,
              height: 140, overflow: "auto", whiteSpace: "pre-wrap",
            }}
          />
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
