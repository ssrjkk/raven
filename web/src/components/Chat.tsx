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
  const currentSessionRef = useRef<string | null>(null);
  const sessionSeqRef = useRef(0);
  const { toast } = useToast();

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const onWsMessage = useCallback((data: { type: string; role?: string; content?: string; session_id?: string; event?: string; profile?: string; detail?: string; data?: Record<string, unknown> }) => {
    if (data.type === "session" && data.session_id) {
      currentSessionRef.current = data.session_id;
      sessionSeqRef.current += 1;
      setCurrentSession(data.session_id);
      setMessages([]);
      setAgentEvents([]);
      return;
    }
    if (data.type === "message") {
      if (data.session_id && currentSessionRef.current && data.session_id !== currentSessionRef.current) return;
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
      if (!currentSessionRef.current && list.length > 0) {
        currentSessionRef.current = list[0].id;
        sessionSeqRef.current += 1;
        setCurrentSession(list[0].id);
      }
    } catch (e) {
      console.error("Failed to load sessions:", e);
      toast("Failed to load sessions", "error");
    }
  }, [toast]);

  const loadMessages = useCallback(async () => {
    if (!currentSessionRef.current) return;
    const seq = ++sessionSeqRef.current;
    const sessionId = currentSessionRef.current;
    try {
      const msgs = await api.sessionMessages(sessionId);
      if (seq === sessionSeqRef.current && currentSessionRef.current === sessionId) {
        setMessages(msgs);
      }
    } catch (e) {
      console.error("Failed to load messages:", e);
      toast("Failed to load messages", "error");
    }
  }, [toast]);

  useEffect(() => { scrollToBottom(); }, [messages]);
  useEffect(() => { loadSessions(); }, [loadSessions]);
  useEffect(() => { if (currentSession) { currentSessionRef.current = currentSession; loadMessages(); } }, [currentSession, loadMessages]);

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
        <div className="flex-1 flex flex-col items-center justify-center text-center px-4 msg-enter">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center text-white text-2xl font-black mb-5"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default), #d946ef)",
              boxShadow: "0 10px 32px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.45))",
            }}
          >
            R
          </div>
          <h2 className="text-2xl font-bold tracking-tight gradient-text">Чем помочь сегодня?</h2>
          <p className="text-sm mt-2 mb-7" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            Начните разговор с агентами или выберите быстрый сценарий
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-xl">
            {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
              <button
                key={label}
                onClick={() => {
                  setInput(prompt);
                  textareaRef.current?.focus();
                }}
                className="suggestion-card"
              >
                <span
                  className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center"
                  style={{
                    backgroundColor: "var(--dt-colors-accent-muted)",
                    color: "var(--dt-colors-accent-default)",
                  }}
                >
                  <Icon size={15} />
                </span>
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
          disabled={!connected}
          placeholder={connected ? "Сообщение… (Enter — отправить, Shift+Enter — новая строка)" : "Подключение к серверу…"}
          className="w-full resize-none bg-transparent px-4 pt-3 pb-1 text-sm outline-none text-primary placeholder:text-[var(--dt-colors-text-tertiary)] disabled:opacity-60"
          style={{ maxHeight: 160 }}
        />
        <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
          <span className="text-[11px]" style={{ color: "var(--dt-colors-text-tertiary)" }}>
            {connected ? "Enter — отправить · Shift+Enter — новая строка" : "Ожидание соединения…"}
          </span>
          <button
            type="submit"
            disabled={!input.trim() || loading || !connected}
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
