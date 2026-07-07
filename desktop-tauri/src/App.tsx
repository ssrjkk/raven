import { useState, useRef, useEffect, useCallback } from "react";

interface Message {
  id: number;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  toolCall?: { name: string; status: string };
}

const WS_URL = "ws://localhost:8000/aios/ws/agent";

function App() {
  const [messages, setMessages] = useState<Message[]>([{ id: 0, role: "system", content: "Connected. Ask me anything — I can read, write, edit files, run commands, search the web, and more." }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [toolCalls, setToolCalls] = useState<{ name: string; status: string }[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolCalls]);

  const connectWs = useCallback(() => {
    const socket = new WebSocket(WS_URL);
    socket.onopen = () => {
      setWs(socket);
    };
    socket.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "message") {
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: "assistant",
          content: data.data?.content || "",
        }]);
      } else if (data.type === "tool_call") {
        const tc = { name: data.data?.name || "?", status: "running" };
        setToolCalls((prev) => [...prev, tc]);
      } else if (data.type === "tool_result") {
        setToolCalls((prev) =>
          prev.map((t) => t.name === data.data?.name ? { ...t, status: "done" } : t)
        );
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: "tool",
          content: `[${data.data?.name}] ${(data.data?.result || "").slice(0, 300)}`,
        }]);
      } else if (data.type === "step_start") {
        const step = data.data?.step || 0;
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: "system",
          content: `Step ${step}`,
        }]);
      } else if (data.type === "final") {
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: "assistant",
          content: data.data?.content || "",
        }]);
        setLoading(false);
        setToolCalls([]);
      } else if (data.type === "error") {
        setMessages((prev) => [...prev, {
          id: Date.now(),
          role: "system",
          content: `Error: ${data.data?.message || "unknown"}`,
        }]);
        setLoading(false);
      }
    };
    socket.onclose = () => {
      setWs(null);
      setTimeout(() => connectWs(), 2000);
    };
    socket.onerror = () => {
      socket.close();
    };
  }, []);

  useEffect(() => {
    connectWs();
  }, [connectWs]);

  const send = () => {
    if (!input.trim() || loading || !ws) return;
    const text = input;
    setInput("");
    setLoading(true);
    setMessages((prev) => [...prev, { id: Date.now(), role: "user", content: text }]);
    ws.send(JSON.stringify({ action: "chat", prompt: text }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#1e1e1e", color: "#d4d4d4", fontFamily: "sans-serif" }}>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #333", background: "#252526", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0, fontSize: 16 }}>RavenCode Desktop</h1>
        <span style={{ fontSize: 12, color: ws ? "#4ec9b0" : "#f44747" }}>
          {ws ? "connected" : "disconnected"}
        </span>
      </header>
      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {messages.map((m) => (
          <div key={m.id} style={{ marginBottom: 10, display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{
              maxWidth: "80%",
              padding: "8px 12px",
              borderRadius: 10,
              background: m.role === "user" ? "#0e639c" : m.role === "system" ? "#2d1b4e" : m.role === "tool" ? "#1a1a2e" : "#2d2d2d",
              border: m.role === "tool" ? "1px solid #333" : "none",
              whiteSpace: "pre-wrap",
              fontSize: 14,
              opacity: m.role === "tool" ? 0.8 : 1,
            }}>
              {m.content}
            </div>
          </div>
        ))}
        {toolCalls.length > 0 && (
          <div style={{ marginBottom: 10, padding: "6px 12px", background: "#1a1a2e", borderRadius: 8, fontSize: 13, border: "1px solid #2a2a4a" }}>
            {toolCalls.map((tc, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                <span style={{ color: tc.status === "running" ? "#e5c07b" : "#4ec9b0" }}>
                  {tc.status === "running" ? ">" : "✓"}
                </span>
                <span>{tc.name}</span>
                <span style={{ color: "#888", fontSize: 12 }}>{tc.status}</span>
              </div>
            ))}
          </div>
        )}
        {loading && toolCalls.length === 0 && (
          <div style={{ color: "#888", padding: 8, fontStyle: "italic" }}>thinking...</div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: 12, borderTop: "1px solid #333", display: "flex", gap: 8, background: "#252526" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask RavenCode..."
          disabled={loading}
          style={{ flex: 1, padding: "10px 14px", borderRadius: 8, border: "1px solid #555", background: "#3c3c3c", color: "#d4d4d4", fontSize: 14, outline: "none" }}
        />
        <button onClick={send} disabled={loading || !ws} style={{
          padding: "10px 20px",
          borderRadius: 8,
          border: "none",
          background: loading || !ws ? "#555" : "#0e639c",
          color: "#fff",
          fontSize: 14,
          cursor: loading || !ws ? "default" : "pointer",
        }}>
          Send
        </button>
      </div>
    </div>
  );
}

export default App;
