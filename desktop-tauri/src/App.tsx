import { useState } from "react"
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom"

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/chat", label: "Chat" },
  { to: "/ide", label: "IDE" },
  { to: "/settings", label: "Settings" },
]

function Dashboard() {
  const [cmd, setCmd] = useState("")
  const [out, setOut] = useState("")

  return (
    <div style={{ padding: 32, fontFamily: "system-ui" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Raven AI - Desktop</h1>
      <p style={{ color: "#888", marginBottom: 24, fontSize: 14 }}>AI-OS-MVP hybrid architecture - Tauri shell</p>

      <input value={cmd} onChange={(e) => setCmd(e.target.value)}
        placeholder="Enter command..."
        style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: "1px solid #333",
          background: "#1a1a1a", color: "#fff", fontSize: 14, marginBottom: 12, outline: "none" }}
        onKeyDown={(e) => e.key === "Enter" && setOut("raven@desktop:~$ " + cmd)}
      />

      <pre style={{ background: "#111", color: "#0f0", padding: 16, borderRadius: 8,
        fontFamily: "monospace", fontSize: 13, minHeight: 200 }}>
        {out || "raven@desktop:~$"}
      </pre>
    </div>
  )
}

export default function App() {
  return (
    <div style={{ background: "#0d0d0d", color: "#fff", minHeight: "100vh" }}>
      <BrowserRouter>
        <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
          <div style={{ display: "flex", flex: 1 }}>
            <nav style={{ width: 200, background: "#111", borderRight: "1px solid #333", padding: 16 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Raven AI</h2>
              {nav.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.to === "/"}
                  style={({ isActive }) => ({
                    display: "block", padding: "8px 12px", borderRadius: 6,
                    marginBottom: 4, fontSize: 14, textDecoration: "none",
                    color: isActive ? "#a78bfa" : "#888",
                    background: isActive ? "#1e1e2e" : "transparent",
                  })}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <main style={{ flex: 1, overflow: "auto" }}>
              <Routes>
                <Route index element={<Dashboard />} />
                <Route path="chat" element={<div style={{ padding: 32, color: "#666" }}>Chat - connect backend to enable</div>} />
                <Route path="ide" element={<div style={{ padding: 32, color: "#666" }}>IDE - open web app for full editor</div>} />
                <Route path="settings" element={<div style={{ padding: 32, color: "#666" }}>Settings page</div>} />
              </Routes>
            </main>
          </div>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #333", fontSize: 11, color: "#666", textAlign: "center" }}>
            <span>Telegram: @ssrjkk | GitHub: github.com/ssrjkk | Email: ray013lefe@gmail.com</span>
            <span style={{ marginLeft: 16, color: "#444" }}>Raven AI v0.2.0</span>
          </div>
        </div>
      </BrowserRouter>
    </div>
  )
}
