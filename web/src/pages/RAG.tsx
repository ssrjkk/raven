import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";

interface RAGResult {
  modality?: string;
  score: number;
  document_id?: string;
  text?: string;
  image_path?: string;
}

interface RAGStats {
  documents?: number;
  chunks?: number;
  total_chars?: number;
  total_images?: number;
  dimension?: number;
  sentence_transformer?: boolean;
  clip_available?: boolean;
  chroma_available?: boolean;
}

type Tab = "search" | "index" | "stats";

export default function RAG() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("search");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // search
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RAGResult[] | null>(null);

  // index
  const [docId, setDocId] = useState("");
  const [docText, setDocText] = useState("");
  const [docSource, setDocSource] = useState("");

  const { data: stats } = useApiQuery<RAGStats>(["ragStats"], () => api.ragStats(), { enabled: tab === "stats" });

  const search = useMutation({
    mutationFn: () => api.ragSearch(query),
    onSuccess: (r) => { setResults(r.results); setError(""); },
    onError: (e: any) => setError(e.message || "Search failed"),
  });

  const indexDoc = useMutation({
    mutationFn: () => api.ragIndexText(docId, docText, docSource),
    onSuccess: (r) => {
      setMsg(`Indexed document '${r.document_id}' (${r.chunks} chunks)`);
      setDocId(""); setDocText(""); setDocSource("");
      qc.invalidateQueries({ queryKey: ["ragStats"] });
    },
    onError: (e: any) => setError(e.message || "Index failed"),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "search", label: "Search" },
    { key: "index", label: "Index Document" },
    { key: "stats", label: "Statistics" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Multi-Modal RAG</h1>

      <div className="flex gap-1 mb-6 border-b border-default">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {tab === "search" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">Cross-Modal Search</h2>
          <div className="flex gap-3 mb-3">
            <input placeholder="Search query..." value={query} onChange={e => setQuery(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <button onClick={() => search.mutate()} disabled={search.isPending || !query}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
              {search.isPending ? "..." : "Search"}
            </button>
          </div>
          {results && (
            <div className="space-y-2 mt-4">
              {results.length === 0 && <p className="text-sm text-tertiary">No results.</p>}
              {results.map((r, i) => (
                <div key={i} className="p-3 rounded-lg bg-tertiary">
                  <div className="flex items-center gap-2 text-xs mb-1">
                    <span className="font-medium">{r.modality?.toUpperCase()}</span>
                    <span>score={r.score.toFixed(4)}</span>
                    <span className="text-tertiary">{r.document_id}</span>
                  </div>
                  <p className="text-sm">{r.text?.slice(0, 300)}</p>
                  {r.image_path && <p className="text-xs mt-1 text-tertiary">СЂСџвЂњВ· {r.image_path}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "index" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">Index Document</h2>
          <div className="space-y-3 mb-3">
            <input placeholder="Document ID" value={docId} onChange={e => setDocId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <input placeholder="Source (optional)" value={docSource} onChange={e => setDocSource(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <textarea placeholder="Document text content..." value={docText} onChange={e => setDocText(e.target.value)}
              rows={8} className="w-full px-3 py-2 rounded-lg text-sm font-mono bg-tertiary text-primary border-default" />
          </div>
          <button onClick={() => indexDoc.mutate()} disabled={indexDoc.isPending || !docId || !docText}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 bg-accent text-white">
            {indexDoc.isPending ? "..." : "Index Document"}
          </button>
        </div>
      )}

      {tab === "stats" && (
        <div className="p-4 rounded-lg bg-secondary">
          <h2 className="text-lg font-semibold mb-3">RAG Statistics</h2>
          {stats === undefined ? (
            <p className="text-sm text-tertiary">Loading...</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                { label: "Documents", value: stats.documents },
                { label: "Chunks", value: stats.chunks },
                { label: "Total Chars", value: stats.total_chars },
                { label: "Total Images", value: stats.total_images },
                { label: "Dimension", value: stats.dimension },
                { label: "SentenceTransformer", value: stats.sentence_transformer ? "РІСљвЂњ" : "РІР‚вЂќ" },
                { label: "CLIP", value: stats.clip_available ? "РІСљвЂњ" : "РІР‚вЂќ" },
                { label: "ChromaDB", value: stats.chroma_available ? "РІСљвЂњ" : "РІР‚вЂќ" },
              ].map(s => (
                <div key={s.label} className="p-3 rounded-lg text-center bg-tertiary">
                  <div className="text-2xl font-bold">{s.value ?? "РІР‚вЂќ"}</div>
                  <div className="text-xs mt-1 text-tertiary">{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
