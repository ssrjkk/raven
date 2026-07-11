import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

interface NodeDatum {
  id: string;
  name: string;
  type: string;
  x: number; y: number; vx: number; vy: number;
}

interface LinkDatum {
  source: string;
  target: string;
  relation: string;
}

type Tab = "graph" | "extract" | "search" | "stats";

const COLORS: Record<string, string> = {
  PERSON: "#3b82f6", ORG: "#10b981", GPE: "#f59e0b",
  TECHNOLOGY: "#8b5cf6", EMAIL: "#ec4899", URL: "#06b6d4",
  VERSION: "#f97316", FILE_PATH: "#14b8a6", DATE: "#eab308",
  PRODUCT: "#a855f7", module: "#6366f1", class: "#ef4444",
  function: "#22c55e", concept: "#6b7280",
};

export default function Knowledge() {
  const [tab, setTab] = useState<Tab>("graph");
  const [nodes, setNodes] = useState<NodeDatum[]>([]);
  const [links, setLinks] = useState<LinkDatum[]>([]);
  const [stats, setStats] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [extractText, setExtractText] = useState("");
  const [extractResult, setExtractResult] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const animRef = useRef<number>(0);

  async function loadGraph() {
    setLoading(true);
    setError("");
    try {
      const r = await api.knowledgeVis();
      const g = r.graph;
      const nodeMap = new Map<string, NodeDatum>();
      const nlist: NodeDatum[] = g.nodes.map((n: any) => {
        const d: NodeDatum = { ...n, x: Math.random() * 600, y: Math.random() * 400, vx: 0, vy: 0 };
        nodeMap.set(n.id, d);
        return d;
      });
      const llist: LinkDatum[] = g.links.map((l: any) => ({
        source: typeof l.source === "object" ? l.source.id : l.source,
        target: typeof l.target === "object" ? l.target.id : l.target,
        relation: l.relation,
      }));
      setNodes(nlist);
      setLinks(llist);
      setStats(r.stats as Record<string, unknown>);
    } catch (e: any) {
      setError(e.message || "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadGraph(); }, []);

  useEffect(() => {
    if (tab !== "graph" || nodes.length === 0) return;
    const W = 700, H = 450;
    let running = true;
    function tick() {
      if (!running) return;
      setNodes(prev => {
        const copy = prev.map(n => ({ ...n }));
        const nodeMap = new Map(copy.map(n => [n.id, n]));
        for (const link of links) {
          const s = nodeMap.get(typeof link.source === "string" ? link.source : (link.source as any).id);
          const t = nodeMap.get(typeof link.target === "string" ? link.target : (link.target as any).id);
          if (!s || !t) continue;
          const dx = t.x - s.x, dy = t.y - s.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (dist - 80) * 0.005;
          s.vx += dx / dist * force;
          s.vy += dy / dist * force;
          t.vx -= dx / dist * force;
          t.vy -= dy / dist * force;
        }
        for (const n of copy) {
          n.vx += (Math.random() - 0.5) * 0.3;
          n.vy += (Math.random() - 0.5) * 0.3;
          n.vx *= 0.95; n.vy *= 0.95;
          n.x += n.vx; n.y += n.vy;
          n.x = Math.max(30, Math.min(W - 30, n.x));
          n.y = Math.max(30, Math.min(H - 30, n.y));
        }
        return copy;
      });
      animRef.current = requestAnimationFrame(tick);
    }
    animRef.current = requestAnimationFrame(tick);
    return () => { running = false; cancelAnimationFrame(animRef.current); };
  }, [tab, nodes.length, links]);

  async function handleExtract() {
    if (!extractText) return;
    setLoading(true); setError(""); setExtractResult("");
    try {
      const r = await api.knowledgeExtract(extractText, "web-ui");
      const ents = r.result.entities.length;
      const rels = r.result.relations.length;
      setExtractResult(`Extracted ${ents} entities, ${rels} relations`);
      loadGraph();
    } catch (e: any) {
      setError(e.message || "Extraction failed");
    } finally { setLoading(false); }
  }

  async function handleSearch() {
    if (!searchQuery) return;
    setLoading(true); setError(""); setSearchResults(null);
    try {
      const r = await api.knowledgeSearch(searchQuery);
      setSearchResults(r.results);
    } catch (e: any) {
      setError(e.message || "Search failed");
    } finally { setLoading(false); }
  }

  const inputStyle: React.CSSProperties = {
    backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)",
    color: "var(--dt-colors-text-primary)", padding: "8px 12px", borderRadius: "6px",
    border: "1px solid", fontSize: "14px", width: "100%", boxSizing: "border-box",
  };
  const btnStyle = { backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold" style={{ color: "var(--dt-colors-text-primary)" }}>Knowledge Graph</h1>

      {error && (
        <div className="px-4 py-2 rounded text-sm" style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "#ef4444" }}>
          {error} <button onClick={() => setError("")} className="ml-3 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>dismiss</button>
        </div>
      )}

      {extractResult && (
        <div className="px-4 py-2 rounded text-sm" style={{ backgroundColor: "rgba(16,185,129,0.15)", color: "#10b981" }}>
          {extractResult}
        </div>
      )}

      <div className="flex gap-1 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["graph", "extract", "search", "stats"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "border-b-2" : ""}`}
            style={{
              color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderColor: tab === t ? "var(--dt-colors-accent-default)" : "transparent",
            }}>
            {t === "graph" ? "Graph" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "graph" && (
        <div>
          <div className="flex gap-2 mb-3">
            <button onClick={loadGraph} disabled={loading}
              className="px-3 py-1.5 rounded text-sm font-medium transition disabled:opacity-40"
              style={btnStyle}>
              {loading ? "Loading..." : "Refresh"}
            </button>
            <span className="text-xs self-center" style={{ color: "var(--dt-colors-text-tertiary)" }}>
              {nodes.length} nodes, {links.length} links
            </span>
          </div>
          <svg ref={svgRef} viewBox="0 0 700 450" className="w-full rounded border"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", maxHeight: "450px" }}>
            {links.map((l, i) => {
              const s = nodes.find(n => n.id === l.source);
              const t = nodes.find(n => n.id === l.target);
              if (!s || !t) return null;
              return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="var(--dt-colors-border-default)" strokeWidth={1} opacity={0.5} />;
            })}
            {nodes.map((n) => (
              <g key={n.id}>
                <circle cx={n.x} cy={n.y} r={6} fill={COLORS[n.type] || "#6b7280"} stroke="var(--dt-colors-bg-primary)" strokeWidth={1.5} />
                <text x={n.x + 9} y={n.y + 3} fontSize={10} fill="var(--dt-colors-text-secondary)">
                  {n.name.length > 20 ? n.name.slice(0, 18) + ".." : n.name}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}

      {tab === "extract" && (
        <div className="space-y-3 max-w-2xl">
          <textarea style={inputStyle} rows={6}
            placeholder="Paste text to extract entities and relations..."
            value={extractText} onChange={(e) => setExtractText(e.target.value)} />
          <button onClick={handleExtract} disabled={loading || !extractText}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40"
            style={btnStyle}>
            {loading ? "Extracting..." : "Extract Knowledge"}
          </button>
        </div>
      )}

      {tab === "search" && (
        <div className="space-y-3 max-w-2xl">
          <div className="flex gap-2">
            <input style={inputStyle} placeholder="Search entities..."
              value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()} />
            <button onClick={handleSearch} disabled={loading || !searchQuery}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-40"
              style={btnStyle}>Search</button>
          </div>
          {searchResults !== null && (
            <div className="space-y-2">
              {searchResults.length === 0 ? (
                <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No results</p>
              ) : (
                searchResults.map((r) => (
                  <div key={r.id} className="p-3 rounded border text-sm"
                    style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                    <span className="font-semibold" style={{ color: COLORS[r.type] || "#6b7280" }}>[{r.type}]</span>
                    {" "}{r.name}
                    {r.neighbors?.length > 0 && (
                      <div className="mt-1 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                        {r.neighbors.slice(0, 5).map((n: any, i: number) => (
                          <div key={i}>{n.relation}: {n.entity} ({n.type})</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      {tab === "stats" && (
        <div className="space-y-3 max-w-lg">
          {Object.keys(stats).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Graph is empty</p>
          ) : (
            Object.entries(stats).map(([key, val]) => (
              <div key={key} className="p-3 rounded border text-sm"
                style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                <div className="font-semibold capitalize" style={{ color: "var(--dt-colors-text-primary)" }}>
                  {key.replace(/_/g, " ")}
                </div>
                <div className="text-xs mt-1" style={{ color: "var(--dt-colors-text-secondary)" }}>
                  {typeof val === "object" ? JSON.stringify(val, null, 2) : String(val)}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
