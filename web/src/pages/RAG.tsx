import { useEffect, useState } from "react";
import { api } from "../api/client";

type Tab = "search" | "index" | "stats";

export default function RAG() {
  const [tab, setTab] = useState<Tab>("search");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<Record<string, any>>({});

  // search
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[] | null>(null);

  // index
  const [docId, setDocId] = useState("");
  const [docText, setDocText] = useState("");
  const [docSource, setDocSource] = useState("");

  async function loadStats() {
    setLoading(true); setError("");
    try {
      const r = await api.ragStats();
      setStats(r);
    } catch (e: any) {
      setError(e.message || "Failed to load stats");
    } finally { setLoading(false); }
  }

  useEffect(() => { if (tab === "stats") loadStats(); }, [tab]);

  async function handleSearch() {
    setResults(null); setError("");
    setLoading(true);
    try {
      const r = await api.ragSearch(query);
      setResults(r.results);
    } catch (e: any) {
      setError(e.message || "Search failed");
    } finally { setLoading(false); }
  }

  async function handleIndex() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.ragIndexText(docId, docText, docSource);
      setMsg(`Indexed document '${r.document_id}' (${r.chunks} chunks)`);
      setDocId(""); setDocText(""); setDocSource("");
    } catch (e: any) {
      setError(e.message || "Index failed");
    } finally { setLoading(false); }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "search", label: "Search" },
    { key: "index", label: "Index Document" },
    { key: "stats", label: "Statistics" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Multi-Modal RAG</h1>

      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {tab === "search" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Cross-Modal Search</h2>
          <div className="flex gap-3 mb-3">
            <input placeholder="Search query..." value={query} onChange={e => setQuery(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            <button onClick={handleSearch} disabled={loading || !query}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              {loading ? "..." : "Search"}
            </button>
          </div>
          {results && (
            <div className="space-y-2 mt-4">
              {results.length === 0 && <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No results.</p>}
              {results.map((r: any, i: number) => (
                <div key={i} className="p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="flex items-center gap-2 text-xs mb-1">
                    <span className="font-medium">{r.modality?.toUpperCase()}</span>
                    <span>score={r.score.toFixed(4)}</span>
                    <span style={{ color: "var(--dt-colors-text-tertiary)" }}>{r.document_id}</span>
                  </div>
                  <p className="text-sm">{r.text?.slice(0, 300)}</p>
                  {r.image_path && <p className="text-xs mt-1" style={{ color: "var(--dt-colors-text-tertiary)" }}>📷 {r.image_path}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "index" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Index Document</h2>
          <div className="space-y-3 mb-3">
            <input placeholder="Document ID" value={docId} onChange={e => setDocId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            <input placeholder="Source (optional)" value={docSource} onChange={e => setDocSource(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            <textarea placeholder="Document text content..." value={docText} onChange={e => setDocText(e.target.value)}
              rows={8} className="w-full px-3 py-2 rounded-lg text-sm font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
          </div>
          <button onClick={handleIndex} disabled={loading || !docId || !docText}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
            {loading ? "..." : "Index Document"}
          </button>
        </div>
      )}

      {tab === "stats" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">RAG Statistics</h2>
          {loading ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Loading...</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                { label: "Documents", value: stats.documents },
                { label: "Chunks", value: stats.chunks },
                { label: "Total Chars", value: stats.total_chars },
                { label: "Total Images", value: stats.total_images },
                { label: "Dimension", value: stats.dimension },
                { label: "SentenceTransformer", value: stats.sentence_transformer ? "✓" : "—" },
                { label: "CLIP", value: stats.clip_available ? "✓" : "—" },
                { label: "ChromaDB", value: stats.chroma_available ? "✓" : "—" },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-2xl font-bold">{s.value ?? "—"}</div>
                  <div className="text-xs mt-1" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
