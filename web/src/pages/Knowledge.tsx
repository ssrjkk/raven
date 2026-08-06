import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type GraphLink, type GraphNode, type KnowledgeSearchEntry } from "../api/client";
import PageHeader from "../components/PageHeader";
import { useApiQuery } from "../hooks/useApiQuery";

type Tab = "graph" | "extract" | "search" | "stats";

const COLORS: Record<string, string> = {
  PERSON: "#3b82f6", ORG: "#10b981", GPE: "#f59e0b",
  TECHNOLOGY: "#8b5cf6", EMAIL: "#ec4899", URL: "#06b6d4",
  VERSION: "#f97316", FILE_PATH: "#14b8a6", DATE: "#eab308",
  PRODUCT: "#a855f7", module: "#6366f1", class: "#ef4444",
  function: "#22c55e", concept: "#6b7280",
};

function simulateForce(nodes: GraphNode[], links: GraphLink[], W: number, H: number) {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  for (const link of links) {
    const s = nodeMap.get(typeof link.source === "string" ? link.source : (link.source as GraphNode).id);
    const t = nodeMap.get(typeof link.target === "string" ? link.target : (link.target as GraphNode).id);
    if (!s || !t) continue;
    const dx = t.x - s.x, dy = t.y - s.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const force = (dist - 80) * 0.005;
    s.vx += (dx / dist) * force;
    s.vy += (dy / dist) * force;
    t.vx -= (dx / dist) * force;
    t.vy -= (dy / dist) * force;
  }
  for (const n of nodes) {
    n.vx += (Math.random() - 0.5) * 0.3;
    n.vy += (Math.random() - 0.5) * 0.3;
    n.vx *= 0.95; n.vy *= 0.95;
    n.x += n.vx; n.y += n.vy;
    n.x = Math.max(30, Math.min(W - 30, n.x));
    n.y = Math.max(30, Math.min(H - 30, n.y));
  }
}

function renderGraph(ctx: CanvasRenderingContext2D, nodes: GraphNode[], links: GraphLink[], W: number, H: number) {
  ctx.clearRect(0, 0, W, H);
  for (const link of links) {
    const s = typeof link.source === "string" ? nodes.find((n) => n.id === link.source) : link.source;
    const t = typeof link.target === "string" ? nodes.find((n) => n.id === link.target) : link.target;
    if (!s || !t) continue;
    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.lineTo(t.x, t.y);
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  for (const n of nodes) {
    ctx.beginPath();
    ctx.arc(n.x, n.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = COLORS[n.type] || "#6b7280";
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.3)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = "#9ca3af";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(n.name.length > 20 ? n.name.slice(0, 18) + ".." : n.name, n.x + 9, n.y);
  }
}

export default function Knowledge() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("graph");
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [stats, setStats] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [extractText, setExtractText] = useState("");
  const [extractResult, setExtractResult] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<KnowledgeSearchEntry[] | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const animRef = useRef<number>(0);
  const frameCount = useRef(0);

  const W = 700, H = 450;

  const { data: graphVis, refetch: graphRefetch } = useApiQuery<{ graph: { nodes: GraphNode[]; links: GraphLink[] }; stats: Record<string, unknown> }>(["knowledgeVis"], () => api.knowledgeVis());

  useEffect(() => {
    if (!graphVis) return;
    const g = graphVis.graph;
    const initialized = g.nodes.map((n) => ({ ...n, x: Math.random() * W, y: Math.random() * H, vx: 0, vy: 0 }));
    nodesRef.current = initialized;
    setLinks(g.links);
    setStats(graphVis.stats);
    frameCount.current = 0;
  }, [graphVis]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || tab !== "graph") return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    frameCount.current = 0;
    let running = true;
    function tick() {
      if (!running) return;
      frameCount.current++;
      if (frameCount.current < 200) {
        simulateForce(nodesRef.current, links, W, H);
      }
      renderGraph(ctx!, nodesRef.current, links, W, H);
      animRef.current = requestAnimationFrame(tick);
    }
    animRef.current = requestAnimationFrame(tick);
    return () => { running = false; cancelAnimationFrame(animRef.current); };
  }, [tab, links]);

  const extract = useMutation({
    mutationFn: () => api.knowledgeExtract(extractText, "web-ui"),
    onSuccess: (r) => {
      setExtractResult(`Extracted ${r.result.entities.length} entities, ${r.result.relations.length} relations`);
      qc.invalidateQueries({ queryKey: ["knowledgeVis"] });
    },
    onError: (e: any) => setError(e.message || "Extraction failed"),
  });

  const search = useMutation({
    mutationFn: () => api.knowledgeSearch(searchQuery),
    onSuccess: (r) => setSearchResults(r.results),
    onError: (e: any) => setError(e.message || "Search failed"),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Graph" subtitle="Extract entities, explore relationships, and search your knowledge base" />

      {error && (
        <div className="px-4 py-2 rounded text-sm bg-danger-subtle text-danger">
          {error} <button onClick={() => setError("")} className="ml-3 text-xs text-tertiary">dismiss</button>
        </div>
      )}

      {extractResult && (
        <div className="px-4 py-2 rounded text-sm bg-success-muted text-success">
          {extractResult}
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
        {(["graph", "extract", "search", "stats"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "tab-active" : "tab-inactive"}`}>
            {t === "graph" ? "Graph" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "graph" && (
        <div>
          <div className="flex gap-2 mb-3">
            <button onClick={() => graphRefetch()} className="btn-ghost">
              Refresh
            </button>
            <span className="text-xs self-center text-tertiary">
              {nodesRef.current.length} nodes, {links.length} links
            </span>
          </div>
          <canvas ref={canvasRef} width={W} height={H}
            className="w-full rounded border border-default bg-secondary"
            style={{ maxHeight: `${H}px` }} />
        </div>
      )}

      {tab === "extract" && (
        <div className="space-y-3 max-w-2xl">
          <textarea className="input-base" rows={6}
            placeholder="Paste text to extract entities and relations..."
            value={extractText} onChange={(e) => setExtractText(e.target.value)} />
          <button onClick={() => extract.mutate()} disabled={extract.isPending || !extractText}
            className="btn-primary">
            {extract.isPending ? "Extracting..." : "Extract Knowledge"}
          </button>
        </div>
      )}

      {tab === "search" && (
        <div className="space-y-3 max-w-2xl">
          <div className="flex gap-2">
            <input className="input-base" placeholder="Search entities..."
              value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search.mutate()} />
            <button onClick={() => search.mutate()} disabled={search.isPending || !searchQuery}
              className="btn-primary">Search</button>
          </div>
          {searchResults !== null && (
            <div className="space-y-2">
              {searchResults.length === 0 ? (
                <p className="text-sm text-tertiary">No results</p>
              ) : (
                searchResults.map((r) => (
                  <div key={r.id} className="card-bordered text-sm p-3">
                    <span className="font-semibold" style={{ color: COLORS[r.type] || "var(--dt-colors-text-tertiary)" }}>[{r.type}]</span>
                    {" "}{r.name}
                    {r.neighbors && r.neighbors.length > 0 && (
                      <div className="mt-1 text-xs text-tertiary">
                        {r.neighbors.slice(0, 5).map((n, i: number) => (
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
            <p className="text-sm text-tertiary">Graph is empty</p>
          ) : (
            Object.entries(stats).map(([key, val]) => (
              <div key={key} className="card-bordered text-sm p-3">
                <div className="font-semibold capitalize text-primary">
                  {key.replace(/_/g, " ")}
                </div>
                <div className="text-xs mt-1 text-secondary">
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
