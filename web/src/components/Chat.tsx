import { useCallback,useEffect, useRef, useState } from "react";

import { api, MessageData,Session } from "../api/client";
import { useWebSocket } from "../hooks/useWebSocket";
import { AgentStream } from "./AgentStream";
import type { AgentEvent } from "./AgentStream";
import MessageBubble from "./MessageBubble";
import PageHeader from "./PageHeader";
import { useToast } from "./Toast";

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [streamVisible, setStreamVisible] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const onWsMessage = useCallback((data: { type: string; role?: string; content?: string; session_id?: string; event?: string; profile?: string; detail?: string; data?: Record<string, unknown> }) => {
    if (data.type === "message") {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: (data.role ?? "assistant") as "assistant", content: data.content ?? "", created_at: new Date().toISOString() },
      ]);
      setLoading(false);
      setTimeout(scrollToBottom, 50);
    }
    if (data.type === "agent_status" && data.event && data.profile) {
      setAgentEvents((prev) => [
        ...prev,
        {
          type: "agent_status",
          event: data.event ?? "",
          profile: data.profile ?? "",
          detail: data.detail,
          data: data.data,
        },
      ]);
      if (data.event === "agent_completed" || data.event === "error") {
        setLoading(false);
      }
      setTimeout(scrollToBottom, 50);
    }
  }, []);

  const { connected, send } = useWebSocket(onWsMessage);

  const loadSessions = useCallback(async () => {
    try {
      const list = await api.sessions();
      setSessions(list);
      if (!currentSession && list.length > 0) setCurrentSession(list[0].id);
    } catch (e) {
      console.error("Failed to load sessions:", e);
      toast("Failed to load sessions", "error");
    }
  }, [currentSession, toast]);

  const loadMessages = useCallback(async () => {
    if (!currentSession) return;
    try {
      const msgs = await api.sessionMessages(currentSession);
      setMessages(msgs);
    } catch (e) {
      console.error("Failed to load messages:", e);
      toast("Failed to load messages", "error");
    }
  }, [currentSession, toast]);

  useEffect(() => { scrollToBottom(); }, [messages]);
  useEffect(() => { loadSessions(); }, [loadSessions]);
  useEffect(() => { if (currentSession) loadMessages(); }, [currentSession, loadMessages]);

  async function sendMessage() {
    if (!input.trim() || loading) return;
    const sessionId = currentSession || "webchat:anon:default";
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: input, created_at: new Date().toISOString() },
    ]);
    setAgentEvents([]);
    setStreamVisible(true);
    send(input, sessionId);
    setInput("");
    setLoading(true);
    setTimeout(scrollToBottom, 50);
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
    } catch (e) {
      console.error("Failed to create session:", e);
      toast("Failed to create session", "error");
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <PageHeader
        title="Chat"
        actions={
          <>
            <span className={connected ? "badge badge-success" : "badge badge-error"}>
              {connected ? "● Connected" : "○ Disconnected"}
            </span>
            <select
              value={currentSession || ""}
              onChange={(e) => setCurrentSession(e.target.value || null)}
              className="input-base px-3 py-1.5 text-xs"
            >
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>{s.id.split(":").slice(0, 2).join(":").slice(-20)}</option>
              ))}
            </select>
            <button onClick={newSession} className="btn-outline px-3 py-1.5 text-xs">
              + New
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-y-auto space-y-2 mb-4">
        {agentEvents.length > 0 && streamVisible && (
          <div className="mb-3">
            <div className="mb-1 flex justify-end">
              <button
                onClick={() => setStreamVisible(false)}
                className="text-xs text-tertiary hover:text-secondary transition"
              >
                Свернуть поток
              </button>
            </div>
            <AgentStream events={agentEvents} />
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {loading && (
          <div className="flex justify-start">
            <div
              className="rounded-2xl rounded-bl-sm px-4 py-3 max-w-[80%]"
              style={{
                backgroundColor: "var(--dt-colors-bg-tertiary)",
                border: "1px solid var(--dt-colors-border-default)",
              }}
            >
              <span className="inline-flex gap-1">
                <span className="typing-dot w-2 h-2 rounded-full" style={{ backgroundColor: "var(--dt-colors-text-tertiary)" }} />
                <span className="typing-dot w-2 h-2 rounded-full" style={{ backgroundColor: "var(--dt-colors-text-tertiary)" }} />
                <span className="typing-dot w-2 h-2 rounded-full" style={{ backgroundColor: "var(--dt-colors-text-tertiary)" }} />
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); sendMessage(); }} className="flex gap-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          className="input-base flex-1 px-4 py-3"
        />
        <button type="submit" disabled={loading} className="btn-primary px-5">
          Send
        </button>
      </form>
    </div>
  );
}