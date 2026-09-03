import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FolderGit2, Plus, Trash2, Pencil } from "lucide-react";

import { api, type ConnectionContext, type LLMProviderInfo } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

type TokenList = "repositories" | "files" | "folders";
const TOKEN_FIELDS: { key: TokenList; label: string; placeholder: string }[] = [
  { key: "repositories", label: "Repositories", placeholder: "org/repo, repo2 (comma separated)" },
  { key: "files", label: "Files", placeholder: "src/a.py, b.ts (comma separated)" },
  { key: "folders", label: "Folders", placeholder: "src/, docs/ (comma separated)" },
];

const EMPTY_FORM = {
  id: undefined as string | undefined,
  name: "",
  provider: "",
  repositories: "",
  files: "",
  folders: "",
  filters: "",
  description: "",
};

function tokensToArray(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

export default function Contexts() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState<string | null>(null); // null = add form closed
  const [form, setForm] = useState(EMPTY_FORM);

  const { data: contextsData, isLoading } = useApiQuery<ConnectionContext[]>(["contexts"], () => api.contexts());
  const { data: providersData } = useApiQuery<LLMProviderInfo[]>(["providers"], () => api.providers());
  const contexts = contextsData ?? [];
  const providers = providersData ?? [];

  function openAdd() {
    setForm(EMPTY_FORM);
    setEditing("");
  }
  function openEdit(c: ConnectionContext) {
    setForm({
      id: c.id,
      name: c.name,
      provider: c.provider,
      repositories: c.repositories.join(", "),
      files: c.files.join(", "),
      folders: c.folders.join(", "),
      filters: c.filters,
      description: c.description,
    });
    setEditing(c.id);
  }

  const save = useMutation({
    mutationFn: () => {
      const editingId = editing;
      const payload = {
        id: form.id,
        name: form.name,
        provider: form.provider,
        repositories: tokensToArray(form.repositories),
        files: tokensToArray(form.files),
        folders: tokensToArray(form.folders),
        filters: form.filters,
        description: form.description,
      };
      if (editingId === "") return api.createContext(payload);
      return api.updateContext(editingId ?? "", payload);
    },
    onSuccess: () => {
      toast(editing === "" ? "Context created" : "Context updated", "success");
      setEditing(null);
      setForm(EMPTY_FORM);
      qc.invalidateQueries({ queryKey: ["contexts"] });
    },
    onError: () => toast("Failed to save context", "error"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteContext(id),
    onSuccess: () => {
      toast("Context deleted", "info");
      qc.invalidateQueries({ queryKey: ["contexts"] });
    },
    onError: () => toast("Failed to delete context", "error"),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={160} height={28} />
        {[1, 2, 3].map((i) => <SkeletonCard key={i} height={80} />)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contexts"
        subtitle="Scoped working sets bound to repositories, files, and a provider"
        actions={
          <button className="btn-primary" onClick={openAdd}>
            <Plus size={15} className="mr-1" /> New Context
          </button>
        }
      />

      {editing !== null && (
        <div className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-primary">{editing === "" ? "Add Context" : "Edit Context"}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-tertiary block mb-1">Name</label>
              <input className="input-base" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Main workspace" />
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Provider</label>
              <select className="input-base" value={form.provider}
                onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                <option value="">(none)</option>
                {providers.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.type})</option>)}
              </select>
            </div>
            {TOKEN_FIELDS.map((f) => (
              <div key={f.key} className="sm:col-span-2">
                <label className="text-xs text-tertiary block mb-1">{f.label}</label>
                <input className="input-base" value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} placeholder={f.placeholder} />
              </div>
            ))}
            <div className="sm:col-span-2">
              <label className="text-xs text-tertiary block mb-1">Filters</label>
              <input className="input-base" value={form.filters}
                onChange={(e) => setForm({ ...form, filters: e.target.value })} placeholder="ext:*.py, exclude:tests" />
            </div>
            <div className="sm:col-span-2">
              <label className="text-xs text-tertiary block mb-1">Description</label>
              <input className="input-base" value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={save.isPending || !form.name} onClick={() => save.mutate()}>
              Save
            </button>
            <button className="btn-ghost" onClick={() => { setEditing(null); setForm(EMPTY_FORM); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {contexts.map((c) => (
          <div key={c.id} className="card p-3 flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <span className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <FolderGit2 size={16} style={{ color: "var(--dt-colors-accent-default)" }} />
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{c.name}</span>
                  {c.provider && <span className="text-[10px] px-1.5 py-0.5 rounded bg-tertiary text-tertiary">{c.provider}</span>}
                </div>
                <div className="text-xs text-tertiary truncate max-w-lg">
                  {[
                    c.repositories.length ? `${c.repositories.length} repo(s)` : "",
                    c.files.length ? `${c.files.length} file(s)` : "",
                    c.folders.length ? `${c.folders.length} folder(s)` : "",
                    c.filters || "",
                  ].filter(Boolean).join(" · ") || "Empty context"}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="btn-soft px-2.5 py-1 text-xs" onClick={() => openEdit(c)}>
                <Pencil size={13} className="mr-1" /> Edit
              </button>
              <button className="btn-soft px-2.5 py-1 text-xs text-danger"
                style={{ backgroundColor: "rgba(239, 68, 68, 0.12)" }}
                onClick={() => { if (window.confirm(`Delete context ${c.name}?`)) del.mutate(c.id); }}>
                <Trash2 size={13} className="mr-1" /> Delete
              </button>
            </div>
          </div>
        ))}
        {contexts.length === 0 && <p className="empty-state">No contexts yet.</p>}
      </div>
    </div>
  );
}
