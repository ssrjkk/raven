import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

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
  const [results, setResults] = useState<{ url: string; title: string; snippet: string }[]>([]);
  const [error, setError] = useState("");
  const [useFailover, setUseFailover] = useState(false);
  const [rawOutput, setRawOutput] = useState("");

  const search = useMutation({
    mutationFn: () => {
      if (!query.trim()) return Promise.reject(new Error("Query required"));
      return useFailover
        ? api.webSearchFailover(query.trim(), parseInt(maxResults) || 10)
        : api.webSearch(query.trim(), provider, parseInt(maxResults) || 10);
    },
    onSuccess: (r) => {
      setResults(r.results || []);
      if (!r.results?.length) setRawOutput("No results found.");
      setError("");
    },
    onError: (e: any) => setError(e.message || "Search failed"),
  });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Web Search</h1>

      <div className="p-4 rounded-lg mb-4 bg-secondary">
        <div className="flex gap-2 mb-3">
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Search query..." onKeyDown={e => e.key === "Enter" && search.mutate()}
            className="flex-1 px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
          <button onClick={() => search.mutate()} disabled={search.isPending || !query.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 bg-accent text-white">
            {search.isPending ? "Searching..." : "Search"}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select value={provider} onChange={e => setProvider(e.target.value)} disabled={useFailover}
            className="px-3 py-1.5 rounded-lg text-sm bg-tertiary text-primary border-default">
            {PROVIDERS.map(p => (
              <option key={p.value} value={p.value} disabled={!p.free && useFailover}>{p.label}{!p.free ? " (API key)" : ""}</option>
            ))}
          </select>

          <label className="flex items-center gap-1.5 text-sm text-secondary">
            <input type="checkbox" checked={useFailover} onChange={e => setUseFailover(e.target.checked)} />
            Auto-failover
          </label>

          <div className="flex items-center gap-1 text-sm text-secondary">
            <span>Max:</span>
            <input value={maxResults} onChange={e => setMaxResults(e.target.value)} type="number" min="1" max="50"
              className="w-16 px-2 py-1 rounded text-sm bg-tertiary text-primary border-default" />
          </div>
        </div>
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}

      {rawOutput && !results.length && (
        <div className="p-4 rounded-lg mb-4 bg-secondary">
          <p className="text-sm text-tertiary">{rawOutput}</p>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-secondary">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
          {results.map((r, i) => (
            <div key={i} className="p-4 rounded-lg bg-secondary">
              <a href={r.url} target="_blank" rel="noopener noreferrer"
                className="text-sm font-semibold hover:underline" style={{ color: "var(--dt-colors-accent-default)" }}>
                {r.title || r.url}
              </a>
              {r.snippet && (
                <p className="text-sm mt-1 text-secondary">
                  {r.snippet}
                </p>
              )}
              <div className="flex gap-3 mt-1 text-xs text-tertiary">
                <span>{r.url}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
