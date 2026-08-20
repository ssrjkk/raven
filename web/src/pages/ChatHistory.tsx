import { Bot, ChevronRight, Clock, MessageSquare, Search, User, X } from "lucide-react";
import { useEffect, useRef,useState } from "react";

import { api, type ChatSearchResult } from "../api/client";

export default function ChatHistory() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChatSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<ChatSearchResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchSeqRef = useRef(0);

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (!q) return;
    const seq = ++searchSeqRef.current;
    setLoading(true);
    setSearched(true);
    setSelected(null);
    try {
      const res = await api.chatSearch(q, 50);
      if (seq !== searchSeqRef.current) return;
      setResults(res.results);
      setTotal(res.total);
    } catch (err) {
      if (seq !== searchSeqRef.current) return;
      console.error("Chat search failed:", err);
      setResults([]);
      setTotal(0);
    } finally {
      if (seq === searchSeqRef.current) setLoading(false);
    }
  }

  function highlightText(text: string, q: string) {
    if (!q.trim()) return text;
    const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
    return parts.map((part, i) =>
      part.toLowerCase() === q.toLowerCase()
        ? <strong key={i} style={{ color: "var(--dt-colors-accent-default)" }}>{part}</strong>
        : part
    );
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-7rem)]">
      {/* Sidebar: search + results */}
      <div className="w-96 shrink-0 flex flex-col gap-3" style={{ minHeight: 0 }}>
        <h1 className="text-xl font-bold shrink-0">Chat History</h1>
        <form onSubmit={handleSearch} className="relative shrink-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-tertiary" />
          <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Search messages..." className="input-base" style={{ paddingLeft: "2.25rem", paddingRight: "2rem" }} />
          {query && (
            <button type="button" onClick={() => { setQuery(""); setResults([]); setSearched(false); }}
              className="absolute right-2 top-1/2 -translate-y-1/2">
              <X className="w-4 h-4 text-tertiary" />
            </button>
          )}
        </form>

        <div className="flex-1 overflow-y-auto space-y-1">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: "var(--dt-colors-accent-default)", borderTopColor: "transparent" }} />
            </div>
          ) : searched && results.length === 0 ? (
            <div className="text-center py-12 text-sm text-tertiary">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No messages found for "{query}"</p>
            </div>
          ) : results.length > 0 ? (
            <>
              <div className="text-xs px-1 pb-1 text-tertiary">
                {total} result{total !== 1 ? "s" : ""}
              </div>
              {results.map((r) => (
                <button key={r.id} onClick={() => setSelected(r)}
                  className="w-full text-left p-2.5 rounded-lg text-sm transition"
                  style={{
                    backgroundColor: selected?.id === r.id ? "var(--dt-colors-bg-tertiary)" : "transparent",
                    border: selected?.id === r.id ? "1px solid var(--dt-colors-border-default)" : "1px solid transparent",
                  }}>
                  <div className="flex items-center gap-1.5 mb-1">
                    {r.role === "user" ? <User className="w-3 h-3" style={{ color: "var(--dt-colors-accent-default)" }} /> : <Bot className="w-3 h-3 text-tertiary" />}
                    <span className="text-[10px] uppercase text-tertiary">{r.role}</span>
                    {r.session_name && <span className="text-[10px] truncate flex-1 text-right text-tertiary">{r.session_name}</span>}
                  </div>
                  <div className="text-xs line-clamp-2 leading-relaxed text-secondary">
                    {highlightText(r.content, query)}
                  </div>
                  <div className="flex items-center gap-1 mt-1">
                    <Clock className="w-2.5 h-2.5 text-tertiary" />
                    <span className="text-[10px] text-tertiary">
                      {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                    </span>
                  </div>
                </button>
              ))}
            </>
          ) : !searched ? (
            <div className="text-center py-16 text-sm text-tertiary">
              <Search className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p>Search through all chat history</p>
              <p className="text-xs mt-1">Type a keyword and press Enter</p>
            </div>
          ) : null}
        </div>
      </div>

      {/* Detail pane */}
      <div className="card flex-1 overflow-hidden flex flex-col" style={{ minHeight: 0 }}>
        {selected ? (
          <>
            <div className="p-4 border-b shrink-0 border-default">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {selected.role === "user" ? <User className="w-4 h-4" style={{ color: "var(--dt-colors-accent-default)" }} /> : <Bot className="w-4 h-4 text-tertiary" />}
                  <span className="text-sm font-medium capitalize">{selected.role}</span>
                </div>
                <span className="text-xs text-tertiary">
                  {selected.created_at ? new Date(selected.created_at).toLocaleString() : ""}
                </span>
              </div>
              {selected.session_name && (
                <div className="text-xs mt-1 text-tertiary">
                  Session: {selected.session_name}
                </div>
              )}
              <div className="text-xs mt-0.5 text-tertiary">
                Session ID: <code className="text-[10px] font-mono">{selected.session_id}</code>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-primary">
                {highlightText(selected.content, query)}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-tertiary">
            <div className="text-center">
              <ChevronRight className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p className="text-sm">Select a result to view</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
