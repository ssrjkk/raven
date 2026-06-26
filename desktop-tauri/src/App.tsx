import { useState, useRef, useEffect } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const API_URL = "http://localhost:8000/v1/chat/completions";

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim()) return;
    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const resp = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "ravencode",
          messages: [...messages, userMsg].map((m) => ({ role: m.role, content: m.content })),
          stream: false,
        }),
      });
      const data = await resp.json();
      const text = data?.choices?.[0]?.message?.content || "(no response)";
      setMessages((prev) => [...prev, { role: "assistant", content: text }]);
    } catch (e: any) {
      setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${e.message}. Start the API server with \`python -m ravencode.api.server\`` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#1e1e1e", color: "#d4d4d4", fontFamily: "sans-serif" }}>
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #333", background: "#252526" }}>
        <h1 style={{ margin: 0, fontSize: 16 }}>RavenCode Desktop</h1>
      </header>
      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12, display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{
              maxWidth: "80%",
              padding: "10px 14px",
              borderRadius: 12,
              background: m.role === "user" ? "#0e639c" : "#2d2d2d",
              whiteSpace: "pre-wrap",
              fontSize: 14,
            }}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && <div style={{ color: "#888", padding: 8 }}>RavenCode is thinking...</div>}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: 12, borderTop: "1px solid #333", display: "flex", gap: 8, background: "#252526" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask RavenCode..."
          style={{ flex: 1, padding: "10px 14px", borderRadius: 8, border: "1px solid #555", background: "#3c3c3c", color: "#d4d4d4", fontSize: 14, outline: "none" }}
        />
        <button onClick={send} disabled={loading} style={{
          padding: "10px 20px",
          borderRadius: 8,
          border: "none",
          background: loading ? "#555" : "#0e639c",
          color: "#fff",
          fontSize: 14,
          cursor: loading ? "default" : "pointer",
        }}>
          Send
        </button>
      </div>
    </div>
  );
}

export default App;
