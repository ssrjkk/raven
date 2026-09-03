import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Pencil, Plug, Plus, Trash2, Zap } from "lucide-react";

import { api, type LLMProviderInfo } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useApiQuery } from "../hooks/useApiQuery";

const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "openrouter",
  "ollama",
  "vllm",
  "groq",
  "azure",
  "vertex",
  "bedrock",
  "copilot",
];

type Form = {
  name: string;
  type: string;
  api_key: string;
  base_url: string;
  model: string;
  enabled: boolean;
};

const EMPTY_FORM: Form = { name: "", type: "openrouter", api_key: "", base_url: "", model: "", enabled: true };

function backendError(e: unknown): string {
  if (e && typeof e === "object" && "message" in e) return String((e as { message: unknown }).message);
  return String(e);
}

export default function Providers() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [mode, setMode] = useState<"closed" | "add" | "edit">("closed");
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [editingOriginal, setEditingOriginal] = useState<string>("");
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const { data: providersData, isLoading } = useApiQuery<LLMProviderInfo[]>(["providers"], () => api.providers());
  const providers = providersData ?? [];

  function openAdd() {
    setForm(EMPTY_FORM);
    setEditingOriginal("");
    setMode("add");
    setTestResult(null);
  }

  function openEdit(p: LLMProviderInfo) {
    setForm({ name: p.name, type: p.type, api_key: "", base_url: p.base_url, model: p.model, enabled: p.enabled });
    setEditingOriginal(p.name);
    setMode("edit");
    setTestResult(null);
  }

  function closeForm() {
    setMode("closed");
    setForm(EMPTY_FORM);
    setEditingOriginal("");
    setTestResult(null);
  }

  const create = useMutation({
    mutationFn: (payload: Form) => api.createProvider(payload),
    onSuccess: () => {
      toast("Provider created", "success");
      closeForm();
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (e: unknown) => toast(`Failed to create: ${backendError(e)}`, "error"),
  });

  const update = useMutation({
    mutationFn: (payload: { originalName: string; data: Partial<LLMProviderInfo> }) =>
      api.updateProvider(payload.originalName, payload.data),
    onSuccess: () => {
      toast("Provider updated", "success");
      closeForm();
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (e: unknown) => toast(`Failed to update: ${backendError(e)}`, "error"),
  });

  const toggleEnabled = useMutation({
    mutationFn: (p: { name: string; enabled: boolean }) =>
      api.updateProvider(p.name, { enabled: p.enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (e: unknown) => toast(`Toggle failed: ${backendError(e)}`, "error"),
  });

  const del = useMutation({
    mutationFn: (name: string) => api.deleteProvider(name),
    onSuccess: () => {
      toast("Provider deleted", "info");
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (e: unknown) => toast(`Delete failed: ${backendError(e)}`, "error"),
  });

  function handleSave() {
    if (mode === "add") {
      create.mutate(form);
    } else if (mode === "edit") {
      const payload: Partial<LLMProviderInfo> = { type: form.type, base_url: form.base_url, model: form.model, enabled: form.enabled };
      if (form.name !== editingOriginal) payload.name = form.name;
      if (form.api_key) payload.api_key = form.api_key;
      update.mutate({ originalName: editingOriginal, data: payload });
    }
  }

  async function runTest() {
    setTestResult(null);
    try {
      const r = await api.testProvider(form.type, form.api_key, form.base_url, form.model);
      setTestResult({ ok: r.ok, msg: `${r.model}: ${r.reply || "connected"}` });
      toast("Connection tested", "success");
    } catch (e) {
      setTestResult({ ok: false, msg: backendError(e) });
      toast("Connection failed", "error");
    }
  }

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
        title="Providers"
        subtitle="LLM connection providers and API keys"
        actions={
          <button className="btn-primary" onClick={openAdd}>
            <Plus size={15} className="mr-1" /> New Provider
          </button>
        }
      />

      {mode !== "closed" && (
        <div className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-primary">{mode === "add" ? "Add Provider" : `Edit ${editingOriginal}`}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-tertiary block mb-1">Name</label>
              <input className="input-base" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="my-openrouter" />
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Type</label>
              <select className="input-base" value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {PROVIDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">API Key</label>
              <input className="input-base" type="password" value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder={mode === "edit" ? "leave empty to keep current" : "sk-..."} />
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Base URL</label>
              <input className="input-base" value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://..." />
            </div>
            <div>
              <label className="text-xs text-tertiary block mb-1">Model</label>
              <input className="input-base" value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="openrouter/openai/o3-mini" />
            </div>
          </div>
          {testResult && (
            <p className={`text-xs ${testResult.ok ? "text-success" : "text-danger"}`}>{testResult.msg}</p>
          )}
          <div className="flex gap-2">
            <button className="btn-primary" disabled={create.isPending || update.isPending || !form.name}
              onClick={handleSave}>
              {mode === "add" ? "Save" : "Update"}
            </button>
            <button className="btn-outline" disabled={!form.type} onClick={runTest}>
              <Zap size={14} className="mr-1" /> Test Connection
            </button>
            <button className="btn-ghost" onClick={closeForm}>Cancel</button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {providers.map((p) => (
          <div key={p.name} className="card p-3 flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <span className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center"
                style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <Plug size={16} style={{ color: p.enabled ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-tertiary)" }} />
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-tertiary text-tertiary">{p.type}</span>
                  {p.enabled ? (
                    <span className="badge badge-success">enabled</span>
                  ) : (
                    <span className="badge badge-warning">disabled</span>
                  )}
                </div>
                <div className="text-xs text-tertiary truncate max-w-md">
                  {p.model || "no model set"}
                  {p.api_key ? " · key set" : " · no key"}
                  {p.base_url ? ` · ${p.base_url}` : ""}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="btn-soft px-2.5 py-1 text-xs"
                onClick={() => toggleEnabled.mutate({ name: p.name, enabled: !p.enabled })}>
                {p.enabled ? "Disable" : "Enable"}
              </button>
              <button className="btn-soft px-2.5 py-1 text-xs" onClick={() => openEdit(p)}>
                <Pencil size={13} className="mr-1" /> Edit
              </button>
              <button className="btn-soft px-2.5 py-1 text-xs text-danger"
                style={{ backgroundColor: "rgba(239, 68, 68, 0.12)" }}
                onClick={() => { if (window.confirm(`Delete provider ${p.name}?`)) del.mutate(p.name); }}>
                <Trash2 size={13} className="mr-1" /> Delete
              </button>
            </div>
          </div>
        ))}
        {providers.length === 0 && <p className="empty-state">No providers configured yet.</p>}
      </div>
    </div>
  );
}
