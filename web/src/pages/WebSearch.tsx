import { useState } from "react";
import { request } from "../api/client";

const PROVIDERS = [
  { value: "duckduckgo", label: "DuckDuckGo", free: true },
  { value: "brave", label: "Brave Search", free: false },
  { value: "perplexity", label: "Perplexity AI", free: false },
  { value: "google", label: "Google Custom Search", free: false },
  { value: "bing", label: "Bing Search", free: false },
  { value: "tavily", label: "Tavily", free: false },
];

export default function WebSearch() {
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState("duckduckgo");
  const [maxResults, setMaxResults] = useState("10");
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [useFailover, setUseFailover] = useState(false);
  const [rawOutput, setRawOutput] = useState("");

  async function handleSearch() {
    if (!query.trim()) return;
    setLoading(true); setError(""); setResults([]); setRawOutput("");
    try {
      const endpoint = useFailover ? "/api/web-search/failover" : "/api/web-search/search";
      const body = useFailover
        ? { query: query.trim(), max_results: parseInt(maxResults) || 10 }
        : { query: query.trim(), provider, max_results: parseInt(maxResults) || 10 };
      const r = await request<any>(endpoint, { method: "POST", body: JSON.stringify(body) });
      setResults(r.results || []);
      if (!r.results?.length) setRawOutput("No results found.");
    } catch (e: any) {
      setError(e.message || "Search failed");
    } finally { setLoading(false); }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Web Search</h1>

      <div className="p-4 rounded-lg mb-4" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
        <div className="flex gap-2 mb-3">
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Search query..." onKeyDown={e => e.key === "Enter" && handleSearch()}
            className="flex-1 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
          <button onClick={handleSearch} disabled={loading || !query.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
            {loading ? "Searching..." : "Search"}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select value={provider} onChange={e => setProvider(e.target.value)} disabled={useFailover}
            className="px-3 py-1.5 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}>
            {PROVIDERS.map(p => (
              <option key={p.value} value={p.value} disabled={!p.free && useFailover}>{p.label}{!p.free ? " (API key)" : ""}</option>
            ))}
          </select>

          <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--dt-colors-text-secondary)" }}>
            <input type="checkbox" checked={useFailover} onChange={e => setUseFailover(e.target.checked)} />
            Auto-failover
          </label>

          <div className="flex items-center gap-1 text-sm" style={{ color: "var(--dt-colors-text-secondary)" }}>
            <span>Max:</span>
            <input value={maxResults} onChange={e => setMaxResults(e.target.value)} type="number" min="1" max="50"
              className="w-16 px-2 py-1 rounded text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
          </div>
        </div>
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}

      {rawOutput && !results.length && (
        <div className="p-4 rounded-lg mb-4" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>{rawOutput}</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium" style={{ color: "var(--dt-colors-text-secondary)" }}>
            {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
          {results.map((r: any, i: number) => (
            <div key={i} className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <a href={r.url} target="_blank" rel="noopener noreferrer"
                className="text-sm font-semibold hover:underline" style={{ color: "var(--dt-colors-accent-default)" }}>
                {r.title || r.url}
              </a>
              {r.snippet && (
                <p className="text-sm mt-1" style={{ color: "var(--dt-colors-text-secondary)" }}>
                  {r.snippet}
                </p>
              )}
              <div className="flex gap-3 mt-1 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                <span>{r.url}</span>
                {r.provider && <span style={{ textTransform: "capitalize" }}>via {r.provider}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
