import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Bot, History, Pencil, Plus, Trash2 } from "lucide-react";

import { api, type AgentInfo, type ConnectionContext, type LLMProviderInfo } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

const EMPTY_FORM = {
  id: undefined as string | undefined,
  name: "",
  provider: "",
  context: "",
  model: "",
  system_prompt: "",
  enabled: true,
};

export default function Agents() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [logOpen, setLogOpen] = useState<string | null>(null);

  const { data: agentsData, isLoading } = useApiQuery<AgentInfo[]>(["agents"], () => api.connectionAgents());
  const { data: providersData } = useApiQuery<LLMProviderInfo[]>(["providers"], () => api.providers());
  const { data: contextsData } = useApiQuery<ConnectionContext[]>(["contexts"], () => api.contexts());
  const agents = agentsData ?? [];
  const providers = providersData ?? [];
  const contexts = contextsData ?? [];

  function openAdd() {
    setForm(EMPTY_FORM);
    setEditing("");
    setLogOpen(null);
  }
  function openEdit(a: AgentInfo) {
    setForm({
      id: a.id,
      name: a.name,
      provider: a.provider,
      context: a.context,
      model: a.model,
      system_prompt: a.system_prompt,
      enabled: a.enabled,
    });
    setEditing(a.id);
    setLogOpen(null);
  }

  const save = useMutation({
    mutationFn: () => {
      const { id, ...payload } = form;
      const editingId = editing;
      if (editingId === "") return api.createAgent(payload);
      return api.updateAgent(editingId ?? "", payload);
    },
    onSuccess: () => {
      toast(editing === "" ? "Agent created" : "Agent updated", "success");
      setEditing(null);
      setForm(EMPTY_FORM);
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: () => toast("Failed to save agent", "error"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteAgent(id),
    onSuccess: () => {
      toast("Agent deleted", "info");
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: () => toast("Failed to delete agent", "error"),
  });

  const providerName = (p: string) => providers.find((x) => x.name === p)?.name || p || "(none)";
  const contextName = (c: string) => contexts.find((x) => x.id === c)?.name || c || "(none)";

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
        title="Agents"
        subtitle="Agent dispatcher — bind agents to providers and contexts, track run history"
        actions={
          <button className="btn-primary" onClick={openAdd}>
            <Plus size={15} className="mr-1" /> New Agent
          </button>
        }
      />

      {editing !== null && (
        <div className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-primary">{editing === "" ? "Add Agent" : "Edit Agent"}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-tertiary block mb-1">Name</label>
              <input className="input-base" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Code Reviewer" />
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Provider</label>
              <select className="input-base" value={form.provider}
                onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                <option value="">(none)</option>
                {providers.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.type})</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Context</label>
              <select className="input-base" value={form.context}
                onChange={(e) => setForm({ ...form, context: e.target.value })}>
                <option value="">(none)</option>
                {contexts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Model</label>
              <input className="input-base" value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="overrides provider default" />
            </div>
            <div className="sm:col-span-2">
              <label className="text-xs text-tertiary block mb-1">System Prompt</label>
              <textarea className="input-base w-full" rows={3} value={form.system_prompt}
                onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                placeholder="You are a senior code reviewer..." />
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              <span className="text-sm text-primary">Enabled</span>
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
        {agents.map((a) => (
          <div key={a.id}>
            <div className="card p-3 flex items-center justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <Bot size={16} style={{ color: "var(--dt-colors-accent-default)" }} />
                </span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.name}</span>
                    {a.enabled ? (
                      <span className="badge badge-success">enabled</span>
                    ) : (
                      <span className="badge badge-warning">disabled</span>
                    )}
                  </div>
                  <div className="text-xs text-tertiary truncate max-w-lg">
                    provider: {providerName(a.provider)} · context: {contextName(a.context)}
                    {a.model ? ` · model: ${a.model}` : ""}
                    {a.history?.length ? ` · ${a.history.length} log entries` : ""}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button className="btn-soft px-2.5 py-1 text-xs"
                  onClick={() => setLogOpen(logOpen === a.id ? null : a.id)}>
                  <History size={13} className="mr-1" /> Log
                </button>
                <button className="btn-soft px-2.5 py-1 text-xs" onClick={() => openEdit(a)}>
                  <Pencil size={13} className="mr-1" /> Edit
                </button>
                <button className="btn-soft px-2.5 py-1 text-xs text-danger"
                  style={{ backgroundColor: "rgba(239, 68, 68, 0.12)" }}
                  onClick={() => { if (window.confirm(`Delete agent ${a.name}?`)) del.mutate(a.id); }}>
                  <Trash2 size={13} className="mr-1" /> Delete
                </button>
              </div>
            </div>

            {logOpen === a.id && (
              <div className="card p-3 mt-2">
                <h3 className="text-xs font-semibold text-primary mb-2">Run history — {a.name}</h3>
                {a.history && a.history.length > 0 ? (
                  <div className="space-y-1 max-h-64 overflow-y-auto">
                    {a.history.map((h, i) => (
                      <div key={i} className="text-xs border-l-2 pl-3 py-0.5"
                        style={{ borderColor: h.role === "user" ? "var(--dt-colors-accent-default)" : "var(--dt-colors-border-default)" }}>
                        <span className="text-tertiary">{new Date(h.ts * 1000).toLocaleString()}</span>{" "}
                        <span className="font-medium">{h.role}</span>
                        <div className="text-secondary whitespace-pre-wrap">{h.content}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-tertiary">No run history yet.</p>
                )}
              </div>
            )}
          </div>
        ))}
        {agents.length === 0 && <p className="empty-state">No agents yet.</p>}
      </div>
    </div>
  );
}
