import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function Plugins() {
  const [installed, setInstalled] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any[]>([]);
  const [topRated, setTopRated] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [installUrl, setInstallUrl] = useState("");
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"installed" | "catalog" | "search" | "install">("installed");

  function refresh() {
    api.plugins().then(setInstalled);
    api.pluginsCatalog().then(setCatalog);
    api.pluginsTop(5).then(setTopRated);
  }

  useEffect(() => { refresh(); }, []);

  async function handleInstall() {
    if (!installUrl) return;
    setMsg("");
    const r = await api.pluginsInstall(installUrl);
    if (r.ok) {
      setMsg(`Installed ${r.name} v${r.version}`);
      setInstallUrl("");
      refresh();
    } else {
      setMsg(`Error: ${r.error}`);
    }
  }

  async function handleUninstall(name: string) {
    const r = await api.pluginsUninstall(name);
    if (r.ok) {
      setMsg(`Uninstalled ${name}`);
      refresh();
    } else {
      setMsg(`Error: ${r.error}`);
    }
  }

  async function handleUpdate(name: string) {
    const r = await api.pluginsUpdate(name);
    if (r.ok) {
      setMsg(`Updated ${name}`);
      refresh();
    } else {
      setMsg(`Error: ${r.error}`);
    }
  }

  async function handleSearch() {
    if (!searchQuery) { setSearchResults(null); return; }
    const r = await api.pluginsSearch(searchQuery);
    setSearchResults(r);
  }

  const categoryColor = (cat: string) => {
    const colors: Record<string, string> = {
      coding: "#3b82f6", automation: "#10b981", unique: "#f59e0b",
      voice: "#8b5cf6", channel: "#ec4899",
    };
    return colors[cat] || "var(--dt-colors-text-tertiary)";
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Plugins</h1>

      {msg && (
        <div className="px-4 py-2 rounded text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}>
          {msg}
          <button onClick={() => setMsg("")} className="ml-3 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["installed", "catalog", "search", "install"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "border-b-2" : ""}`}
            style={{
              color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderColor: tab === t ? "var(--dt-colors-accent-default)" : "transparent",
            }}>
            {t === "installed" ? `Installed (${installed.length})` : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "installed" && (
        <div className="space-y-3">
          {installed.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No plugins installed</p>
          ) : (
            installed.map((p) => (
              <div key={p.id || p.name} className="p-4 rounded border text-sm"
                style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="font-semibold">{p.name}</span>
                    <span className="ml-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>v{p.version}</span>
                    <span className="ml-2 text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: categoryColor(p.category), color: "#fff" }}>{p.category}</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleUpdate(p.name)}
                      className="px-2 py-1 rounded text-xs font-medium transition"
                      style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
                      Update
                    </button>
                    <button onClick={() => handleUninstall(p.name)}
                      className="px-2 py-1 rounded text-xs font-medium transition"
                      style={{ backgroundColor: "rgba(239,68,68,0.15)", color: "#ef4444" }}>
                      Uninstall
                    </button>
                  </div>
                </div>
                <p style={{ color: "var(--dt-colors-text-secondary)" }}>{p.description}</p>
                <div className="mt-1 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                  {p.author && <span>by {p.author} &middot; </span>}
                  <span>Status: {p.status}</span>
                  {p.installed_at && <span> &middot; {new Date(p.installed_at).toLocaleDateString()}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {tab === "catalog" && (
        <div className="space-y-4">
          {topRated.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--dt-colors-text-secondary)" }}>Top Rated</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {topRated.map((p) => (
                  <div key={p.id} className="p-3 rounded border text-sm"
                    style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                    <div className="font-semibold">{p.name}</div>
                    <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{p.description.slice(0, 100)}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                      <span style={{ color: "#f59e0b" }}>★ {p.rating.toFixed(1)}</span>
                      <span className="px-1 py-0.5 rounded text-[10px]" style={{ backgroundColor: categoryColor(p.category), color: "#fff" }}>{p.category}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--dt-colors-text-secondary)" }}>All Plugins ({catalog.length})</h3>
            {catalog.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Catalog empty (no remote configured)</p>
            ) : (
              catalog.map((p) => (
                <div key={p.id} className="p-3 rounded border text-sm mb-2"
                  style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-semibold">{p.name}</span>
                      <span className="ml-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>v{p.version}</span>
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: categoryColor(p.category), color: "#fff" }}>{p.category}</span>
                    </div>
                    <button onClick={() => { setInstallUrl(p.id); setTab("install"); }}
                      className="px-3 py-1 rounded text-xs font-medium transition"
                      style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
                      Install
                    </button>
                  </div>
                  <p className="mt-1 text-xs" style={{ color: "var(--dt-colors-text-secondary)" }}>{p.description}</p>
                  {p.tags?.length > 0 && (
                    <div className="mt-1 flex gap-1">
                      {p.tags.map((t: string) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-tertiary)" }}>{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {tab === "search" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input
              className="flex-1 px-3 py-2 rounded border text-sm"
              style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
              placeholder="Search plugins..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            />
            <button onClick={handleSearch}
              className="px-4 py-2 rounded-lg text-sm font-medium transition"
              style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
              Search
            </button>
          </div>
          {searchResults !== null && (
            <div className="space-y-2">
              {searchResults.length === 0 ? (
                <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No results</p>
              ) : (
                searchResults.map((p) => (
                  <div key={p.id} className="p-3 rounded border text-sm"
                    style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)" }}>
                    <span className="font-semibold">{p.name}</span>
                    <span className="ml-2 text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>v{p.version}</span>
                    <p className="text-xs mt-1" style={{ color: "var(--dt-colors-text-secondary)" }}>{p.description}</p>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      {tab === "install" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Plugin URL or path"
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleInstall()}
          />
          <button onClick={handleInstall}
            className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            Install Plugin
          </button>
        </div>
      )}
    </div>
  );
}
