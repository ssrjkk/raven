import { useEffect, useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

interface PluginManifest {
  id?: string;
  name: string;
  version: string;
  description?: string;
  author?: string;
  category?: string;
  status?: string;
  installed_at?: string;
  rating?: number;
  tags?: string[];
}

export default function Plugins() {
  const [installed, setInstalled] = useState<PluginManifest[]>([]);
  const [catalog, setCatalog] = useState<PluginManifest[]>([]);
  const [topRated, setTopRated] = useState<PluginManifest[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<PluginManifest[] | null>(null);
  const [installUrl, setInstallUrl] = useState("");
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"installed" | "catalog" | "search" | "install">("installed");

  function refresh() {
    api.plugins().then(setInstalled).catch(e => console.error("plugins installed:", e));
    api.pluginsCatalog().then(setCatalog).catch(e => console.error("plugins catalog:", e));
    api.pluginsTop(5).then(setTopRated).catch(e => console.error("plugins top:", e));
  }

  useEffect(() => { refresh(); }, []);

  async function handleInstall() {
    try {
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
    } catch (e) {
      console.error("install plugin:", e);
    }
  }

  async function handleUninstall(name: string) {
    try {
      const r = await api.pluginsUninstall(name);
      if (r.ok) {
        setMsg(`Uninstalled ${name}`);
        refresh();
      } else {
        setMsg(`Error: ${r.error}`);
      }
    } catch (e) {
      console.error("uninstall plugin:", e);
    }
  }

  async function handleUpdate(name: string) {
    try {
      const r = await api.pluginsUpdate(name);
      if (r.ok) {
        setMsg(`Updated ${name}`);
        refresh();
      } else {
        setMsg(`Error: ${r.error}`);
      }
    } catch (e) {
      console.error("update plugin:", e);
    }
  }

  async function handleSearch() {
    try {
      if (!searchQuery) { setSearchResults(null); return; }
      const r = await api.pluginsSearch(searchQuery);
      setSearchResults(r);
    } catch (e) {
      console.error("search plugins:", e);
    }
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
      <PageHeader title="Plugins" subtitle="Install, manage, and discover plugins" />

      {msg && (
        <div className="px-4 py-2 rounded text-sm btn-tertiary">
          {msg}
          <button onClick={() => setMsg("")} className="ml-3 text-xs text-tertiary">dismiss</button>
        </div>
      )}

      <div className="flex gap-1 border-b border-default">
        {(["installed", "catalog", "search", "install"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "tab-active" : "tab-inactive"}`}>
            {t === "installed" ? `Installed (${installed.length})` : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "installed" && (
        <div className="space-y-3">
          {installed.length === 0 ? (
            <p className="empty-state">No plugins installed yet</p>
          ) : (
            installed.map((p) => (
              <div key={p.id || p.name} className="card text-sm">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="font-semibold">{p.name}</span>
                    <span className="ml-2 text-xs text-tertiary">v{p.version}</span>
                    <span className="ml-2 text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: categoryColor(p.category ?? ""), color: "#fff" }}>{p.category}</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleUpdate(p.name)}
                      className="btn-soft px-2.5 py-1 text-xs">
                      Update
                    </button>
                    <button onClick={() => handleUninstall(p.name)}
                      className="btn-soft px-2.5 py-1 text-xs text-danger" style={{ backgroundColor: "rgba(239, 68, 68, 0.12)" }}>
                      Uninstall
                    </button>
                  </div>
                </div>
                <p className="text-secondary">{p.description}</p>
                <div className="mt-1 text-xs text-tertiary">
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
              <h3 className="text-sm font-semibold mb-2 text-secondary">Top Rated</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {topRated.map((p) => (
                  <div key={p.id} className="card-bordered text-sm p-3">
                    <div className="font-semibold">{p.name}</div>
                    <div className="text-xs text-tertiary">{(p.description ?? "").slice(0, 100)}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-tertiary">
                      <span style={{ color: "#f59e0b" }}>★ {(p.rating ?? 0).toFixed(1)}</span>
                      <span className="px-1 py-0.5 rounded text-[10px]" style={{ backgroundColor: categoryColor(p.category ?? ""), color: "#fff" }}>{p.category}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <h3 className="text-sm font-semibold mb-2 text-secondary">All Plugins ({catalog.length})</h3>
            {catalog.length === 0 ? (
              <p className="empty-state">Catalog empty (no remote configured)</p>
            ) : (
              catalog.map((p) => (
                <div key={p.id} className="card-bordered text-sm mb-2 p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-semibold">{p.name}</span>
                      <span className="ml-2 text-xs text-tertiary">v{p.version}</span>
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: categoryColor(p.category ?? ""), color: "#fff" }}>{p.category}</span>
                    </div>
                    <button onClick={() => { setInstallUrl(p.id ?? ""); setTab("install"); }}
                      className="btn-soft px-3 py-1 text-xs">
                      Install
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-secondary">{p.description}</p>
                  {p.tags && p.tags.length > 0 && (
                    <div className="mt-1 flex gap-1">
                      {p.tags.map((t: string) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-tertiary text-tertiary">{t}</span>
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
              className="input-base flex-1"
              placeholder="Search plugins..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            />
            <button onClick={handleSearch} className="btn-primary">
              Search
            </button>
          </div>
          {searchResults !== null && (
            <div className="space-y-2">
              {searchResults.length === 0 ? (
                <p className="empty-state">No results for "{searchQuery}"</p>
              ) : (
                searchResults.map((p) => (
                  <div key={p.id} className="card-bordered text-sm p-3">
                    <span className="font-semibold">{p.name}</span>
                    <span className="ml-2 text-xs text-tertiary">v{p.version}</span>
                    <p className="text-xs mt-1 text-secondary">{p.description}</p>
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
            className="input-base"
            placeholder="Plugin URL or path"
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleInstall()}
          />
          <button onClick={handleInstall} className="btn-primary">
            Install Plugin
          </button>
        </div>
      )}
    </div>
  );
}
