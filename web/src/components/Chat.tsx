import { useState, useEffect, useRef, useCallback } from "react";
import { api, Session, MessageData } from "../api/client";
import { useWebSocket } from "../hooks/useWebSocket";
import Sidebar from "./Sidebar";
import MessageBubble from "./MessageBubble";

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const onWsMessage = useCallback((data: { type: string; role: string; content: string; session_id: string }) => {
    if (data.type === "message") {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: data.role as "assistant", content: data.content, created_at: new Date().toISOString() },
      ]);
      setLoading(false);
    }
  }, []);

  const { connected, send } = useWebSocket(onWsMessage);

  useEffect(() => { loadSessions(); }, []);
  useEffect(() => { if (currentSession) loadMessages(); }, [currentSession]);

  async function loadSessions() {
    try {
      const list = await api.sessions();
      setSessions(list);
      if (!currentSession && list.length > 0) setCurrentSession(list[0].id);
    } catch { /* ignore */ }
  }

  async function loadMessages() {
    if (!currentSession) return;
    try {
      const msgs = await api.sessionMessages(currentSession);
      setMessages(msgs);
    } catch { /* ignore */ }
  }

  async function sendMessage() {
    if (!input.trim() || loading) return;
    const sessionId = currentSession || `webchat:anon:default`;
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: input, created_at: new Date().toISOString() },
    ]);
    send(input, sessionId);
    setInput("");
    setLoading(true);
  }

  async function newSession() {
    try {
      const s = await api.createSession();
      setSessions((prev) => [
        { id: s.id, channel: "webchat", user_id: "web_user", agent_id: "assistant", updated_at: new Date().toISOString() },
        ...prev,
      ]);
      setCurrentSession(s.id);
      setMessages([]);
    } catch { /* ignore */ }
  }

  return (
    <div className="flex h-screen">
      <Sidebar
        sessions={sessions}
        currentSession={currentSession}
        onSelect={setCurrentSession}
        onNew={newSession}
      />
      <div className="flex-1 flex flex-col">
        <header className="h-14 flex items-center px-6 border-b border-gray-800/50 bg-gray-900/50">
          <span className="text-sm text-gray-400">
            {connected ? "● Connected" : "○ Disconnected"}
          </span>
          {currentSession && (
            <span className="ml-4 text-xs text-gray-600 font-mono truncate">
              {currentSession}
            </span>
          )}
        </header>
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-800/50 border border-gray-700/50 rounded-2xl rounded-bl-sm px-4 py-3 max-w-[80%]">
                <span className="inline-flex gap-1">
                  <span className="typing-dot w-2 h-2 bg-gray-400 rounded-full" />
                  <span className="typing-dot w-2 h-2 bg-gray-400 rounded-full" />
                  <span className="typing-dot w-2 h-2 bg-gray-400 rounded-full" />
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <div className="border-t border-gray-800/50 p-4 bg-gray-900/30">
          <form
            onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
            className="flex gap-3 max-w-4xl mx-auto"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a message..."
              className="flex-1 bg-gray-800/60 border border-gray-700/50 rounded-xl px-4 py-3 text-sm
                         text-gray-100 placeholder-gray-500
                         focus:outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20
                         transition"
            />
            <button
              type="submit"
              disabled={loading}
              className="bg-violet-600 hover:bg-violet-500 disabled:bg-violet-800/50
                         text-white px-5 py-2 rounded-xl text-sm font-medium transition"
            >
              Send
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
