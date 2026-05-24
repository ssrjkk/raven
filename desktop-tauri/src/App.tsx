import { useState } from "react"

export default function App() {
  const [cmd, setCmd] = useState("")
  const [out, setOut] = useState("")

  return (
    <div style={{ padding: 32, fontFamily: "system-ui", background: "#0d0d0d", color: "#fff", minHeight: "100vh" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>
        Raven AI — Desktop
      </h1>
      <p style={{ color: "#888", marginBottom: 24, fontSize: 14 }}>
        AI-OS-MVP hybrid architecture • Tauri shell
      </p>

      <input
        value={cmd}
        onChange={(e) => setCmd(e.target.value)}
        placeholder="Enter command..."
        style={{
          width: "100%", padding: "10px 14px", borderRadius: 8,
          border: "1px solid #333", background: "#1a1a1a", color: "#fff",
          fontSize: 14, marginBottom: 12, outline: "none",
        }}
        onKeyDown={(e) => e.key === "Enter" && setOut("executed: " + cmd)}
      />

      <button
        onClick={() => setOut("executed: " + cmd)}
        style={{
          padding: "10px 24px", borderRadius: 8, border: "none",
          background: "#fff", color: "#000", fontWeight: 600,
          cursor: "pointer", fontSize: 14, marginBottom: 16,
        }}
      >
        Run
      </button>

      <pre style={{
        background: "#111", color: "#0f0", padding: 16, borderRadius: 8,
        fontFamily: "monospace", fontSize: 13, minHeight: 200,
      }}>
        {out || "raven@ai-os:~$"}
      </pre>
    </div>
  )
}
