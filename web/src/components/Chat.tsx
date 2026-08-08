import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronsUpDown, FileCode2, MessageSquarePlus, RefreshCw, SendHorizontal, Sparkles, Wrench } from "lucide-react";

import { api, MessageData, Session } from "../api/client";
import { useWebSocket } from "../hooks/useWebSocket";
import { AgentStream, type AgentEvent } from "./AgentStream";
import MessageBubble from "./MessageBubble";
import PageHeader from "./PageHeader";
import { useToast } from "./Toast";

const SUGGESTIONS = [
  { icon: Sparkles, label: "Спланировать фичу", prompt: "Составь детальный план реализации новой фичи в проекте" },
  { icon: FileCode2, label: "Рефакторинг", prompt: "Проанализируй код и предложи рефакторинг проблемных мест" },
  { icon: Wrench, label: "Диагностика", prompt: "Проверь проект на ошибки и предложи исправления" },
  { icon: RefreshCw, label: "Git-статус", prompt: "Покажи git-статус и последние изменения в репозитории" },
];

function sessionLabel(s: Session): string {
  const tail = s.id.split(":").pop() ?? s.id;
  return tail.length > 24 ? `${tail.slice(0, 22)}…` : tail;
}

export default function Chat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [streamVisible, setStreamVisible] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

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
  }, [scrollToBottom]);

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

  function autogrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function sendMessage() {
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
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setLoading(true);
    setTimeout(scrollToBottom, 50);
  }

  function onComposerKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
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
      setAgentEvents([]);
    } catch (e) {
      console.error("Failed to create session:", e);
      toast("Failed to create session", "error");
    }
  }

  const showWelcome = messages.length === 0 && agentEvents.length === 0 && !loading;

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <PageHeader
        title="Chat"
        subtitle="Разговоры с агентами Raven"
        actions={
          <>
            <span className={connected ? "badge badge-success" : "badge badge-error"}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "currentColor" }} />
              {connected ? "Online" : "Offline"}
            </span>
            {sessions.length > 0 && (
              <div className="relative">
                <select
                  value={currentSession || ""}
                  onChange={(e) => setCurrentSession(e.target.value || null)}
                  className="input-base px-3 py-1.5 text-xs pr-8 appearance-none cursor-pointer"
                  aria-label="Session"
                >
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>{sessionLabel(s)}</option>
                  ))}
                </select>
                <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2" size={14} />
              </div>
            )}
            <button onClick={newSession} className="btn-outline px-3 py-1.5 text-xs flex items-center gap-1.5">
              <MessageSquarePlus className="w-3.5 h-3.5" />
              New
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
              className="rounded-2xl rounded-bl-sm px-4 py-3"
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

      {showWelcome && (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center text-white text-2xl font-black mb-4"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default), #d946ef)",
              boxShadow: "0 8px 28px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.4))",
            }}
          >
            R
          </div>
          <h2 className="text-xl font-bold tracking-tight">Чем помочь сегодня?</h2>
          <p className="text-sm mt-1 mb-6" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            Начните разговор с агентами или выберите быстрый сценарий
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
            {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
              <button
                key={label}
                onClick={() => {
                  setInput(prompt);
                  textareaRef.current?.focus();
                }}
                className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-sm font-medium transition hover:scale-[1.02] active:scale-[0.98]"
                style={{
                  backgroundColor: "var(--dt-colors-bg-tertiary)",
                  color: "var(--dt-colors-text-secondary)",
                  border: "1px solid var(--dt-colors-border-default)",
                }}
              >
                <Icon size={15} className="shrink-0" style={{ color: "var(--dt-colors-accent-default)" }} />
                <span className="truncate">{label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <form
        onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
        className="composer"
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => { setInput(e.target.value); autogrow(); }}
          onKeyDown={onComposerKeyDown}
          rows={1}
          placeholder="Сообщение… (Enter — отправить, Shift+Enter — новая строка)"
          className="w-full resize-none bg-transparent px-4 pt-3 pb-1 text-sm outline-none text-primary placeholder:text-[var(--dt-colors-text-tertiary)]"
          style={{ maxHeight: 160 }}
        />
        <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
          <span className="text-[11px]" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            Enter — отправить · Shift+Enter — новая строка
          </span>
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="btn-primary px-4 py-2 rounded-xl"
            aria-label="Send message"
          >
            <SendHorizontal className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
}
