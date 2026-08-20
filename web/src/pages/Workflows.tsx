import { useEffect, useRef,useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

interface TemplateStep {
  description: string;
  tool: string | null;
  params: Record<string, string>;
}

interface EditStep extends TemplateStep {
  uid: string;
}

interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  trigger: string;
  icon: string;
  default_schedule: string | null;
  default_interval: number | null;
  config_schema: { properties?: Record<string, { title?: string; type?: string; default?: string }> };
  predefined_steps: TemplateStep[];
  steps_goal: string | null;
  system_prompt: string | null;
}

interface WorkflowRun {
  id: string;
  template_id: string;
  template_name: string;
  status: string;
  started_at: string;
}

export default function Workflows() {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [activeCat, setActiveCat] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [configs, setConfigs] = useState<Record<string, Record<string, string>>>({});
  const [msg, setMsg] = useState("");
  const [showBuilder, setShowBuilder] = useState<string | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [showRuns, setShowRuns] = useState(false);
  const [editSteps, setEditSteps] = useState<EditStep[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const dragOverIdx = useRef<number | null>(null);

  useEffect(() => {
    api.workflowsList().then((r) => setTemplates(r as WorkflowTemplate[])).catch(e => console.error("templates:", e));
    api.workflowCategories().then((d) => setCategories(d.categories)).catch(e => console.error("categories:", e));
    api.workflowRuns()
      .then((d) => setRuns(d.runs ?? []))
      .catch(() => setRuns([]));
  }, []);

  const filtered = activeCat === "all" ? templates : templates.filter((t) => t.category === activeCat);

  function updateConfig(tid: string, key: string, value: string) {
    setConfigs((prev) => ({ ...prev, [tid]: { ...(prev[tid] || {}), [key]: value } }));
  }

  async function runNow(t: WorkflowTemplate) {
    setMsg(`Running ${t.name}...`);
    try {
      const r = await api.workflowInstantiate(t.id, configs[t.id] || {});
      setMsg(r.ok ? `Task created: ${r.task_id}` : "Failed");
    } catch (e) {
      setMsg(`Error: ${e}`);
    }
  }

  async function schedule(t: WorkflowTemplate) {
    setMsg(`Scheduling ${t.name}...`);
    try {
      const r = await api.workflowSchedule(t.id, configs[t.id] || {});
      setMsg(r.ok ? `Scheduled: ${r.routine_id}` : "Failed");
    } catch (e) {
      setMsg(`Error: ${e}`);
    }
  }

  // ── Drag & Drop step reorder ──────────────────────────
  function openBuilder(t: WorkflowTemplate) {
    setShowBuilder(t.id);
    setEditSteps(t.predefined_steps ? t.predefined_steps.map((s) => ({ ...s, params: { ...s.params }, uid: crypto.randomUUID() })) : []);
  }

  function closeBuilder() {
    setShowBuilder(null);
    setEditSteps([]);
  }

  function addStep() {
    setEditSteps((prev) => [...prev, { description: "", tool: null, params: {}, uid: crypto.randomUUID() }]);
  }

  function removeStep(idx: number) {
    setEditSteps((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateStep(idx: number, field: keyof TemplateStep, value: string | null) {
    setEditSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  }

  function moveStep(from: number, to: number) {
    if (to < 0 || to >= editSteps.length) return;
    setEditSteps((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  function onDragStart(idx: number) {
    setDragIdx(idx);
  }

  function onDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    dragOverIdx.current = idx;
  }

  function onDrop() {
    if (dragIdx !== null && dragOverIdx.current !== null && dragIdx !== dragOverIdx.current) {
      moveStep(dragIdx, dragOverIdx.current);
    }
    setDragIdx(null);
    dragOverIdx.current = null;
  }

  async function saveSteps(t: WorkflowTemplate) {
    try {
      await api.workflowSteps(t.id, editSteps);
      setMsg(`Steps saved for ${t.name}`);
      closeBuilder();
    } catch (e) {
      setMsg(`Error saving steps: ${e}`);
    }
  }

  // ── Generate steps from goal ──────────────────────────
  async function generateSteps(t: WorkflowTemplate) {
    if (!t.steps_goal) return;
    setMsg(`Generating steps for ${t.name}...`);
    try {
      const r = await api.workflowGenerateSteps(t.id);
      setEditSteps(r.steps.map((s) => ({ ...s, uid: crypto.randomUUID() })));
      setMsg("Steps generated");
    } catch (e) {
      setMsg(`Error: ${e}`);
    }
  }

  // ── Edit step params as JSON ──────────────────────────
  function updateStepParam(idx: number, key: string, value: string) {
    setEditSteps((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], params: { ...next[idx].params, [key]: value } };
      return next;
    });
  }

  function removeStepParam(idx: number, key: string) {
    setEditSteps((prev) => {
      const next = [...prev];
      const p = { ...next[idx].params };
      delete p[key];
      next[idx] = { ...next[idx], params: p };
      return next;
    });
  }

  function addStepParam(idx: number) {
    setEditSteps((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], params: { ...next[idx].params, "": "" } };
      return next;
    });
  }

  const statusBadge: Record<string, string> = {
    running: "badge badge-info", completed: "badge badge-success", failed: "badge badge-error", pending: "badge badge-warning",
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflows"
        subtitle="Automate recurring tasks with reusable workflow templates"
        actions={
          <button onClick={() => setShowRuns(!showRuns)} className="btn-outline">
            {showRuns ? "Templates" : `Runs (${runs.length})`}
          </button>
        }
      />

      {msg && (
        <div className="px-4 py-2 rounded text-sm flex items-center justify-between btn-tertiary">
          <span>{msg}</span>
          <button onClick={() => setMsg("")} className="text-xs text-tertiary">dismiss</button>
        </div>
      )}

      {showRuns ? (
        <div className="space-y-2">
          {runs.length === 0 && <p className="text-sm text-tertiary">No runs yet</p>}
          {runs.map((run) => (
            <div key={run.id} className="card flex items-center justify-between p-3">
              <div>
                <span className="font-medium text-sm">{run.template_name}</span>
                <span className="ml-3 text-xs text-tertiary">{run.started_at}</span>
              </div>
              <span className={`${statusBadge[run.status] || "badge badge-accent"}`}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "currentColor" }} />
                {run.status}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <>
          {/* Category filter */}
          <div className="flex gap-2 flex-wrap">
            <button onClick={() => setActiveCat("all")}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition ${activeCat === "all" ? "border" : ""}`}
              style={{ backgroundColor: activeCat === "all" ? "var(--dt-colors-accent-muted)" : "var(--dt-colors-bg-secondary)", color: activeCat === "all" ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderColor: activeCat === "all" ? "var(--dt-colors-accent-subtle)" : "transparent" }}>
              All
            </button>
            {categories.map((cat) => (
              <button key={cat} onClick={() => setActiveCat(cat)}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition ${activeCat === cat ? "border" : ""}`}
                style={{ backgroundColor: activeCat === cat ? "var(--dt-colors-accent-muted)" : "var(--dt-colors-bg-secondary)", color: activeCat === cat ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderColor: activeCat === cat ? "var(--dt-colors-accent-subtle)" : "transparent" }}>
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>

          {/* Template cards */}
          <div className="grid gap-4">
            {filtered.map((t) => (
              <div key={t.id} className="card">
                <button
                  onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                  className="w-full flex items-center justify-between p-4 text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xl">{t.icon || "⚙"}</span>
                    <div>
                      <div className="font-semibold">{t.name}</div>
                      <div className="text-sm text-tertiary">{t.description}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {t.predefined_steps && t.predefined_steps.length > 0 && (
                      <span className="text-xs text-tertiary">
                        {t.predefined_steps.length} steps
                      </span>
                    )}
                    <span className="chip">
                      {t.trigger}
                    </span>
                    <span className={`text-lg transition text-tertiary ${expanded === t.id ? "rotate-180" : ""}`}>▾</span>
                  </div>
                </button>

                {expanded === t.id && (
                  <div className="px-4 pb-4 space-y-4 border-t pt-4 border-default">
                    {/* System prompt / Steps goal */}
                    {(t.system_prompt || t.steps_goal) && (
                      <div className="space-y-1">
                        {t.system_prompt && (
                          <div>
                            <span className="text-xs font-medium text-tertiary">System prompt: </span>
                            <span className="text-xs text-secondary">{t.system_prompt}</span>
                          </div>
                        )}
                        {t.steps_goal && (
                          <div>
                            <span className="text-xs font-medium text-tertiary">Goal: </span>
                            <span className="text-xs text-secondary">{t.steps_goal}</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Predefined steps visualization */}
                    {t.predefined_steps && t.predefined_steps.length > 0 && (
                      <div className="space-y-1.5">
                        <h4 className="text-sm font-medium text-secondary">Steps</h4>
                        <div className="space-y-1">
                          {t.predefined_steps.map((step, si) => (
                            <div key={si} className="flex items-center gap-3 text-xs p-2 rounded bg-primary">
                              <span className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium bg-accent-muted text-accent">
                                {si + 1}
                              </span>
                              <span className="text-primary">{step.description}</span>
                              {step.tool && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-tertiary text-tertiary">
                                  {step.tool}
                                </span>
                              )}
                              {Object.keys(step.params).length > 0 && (
                                <span className="text-[10px] text-tertiary">
                                  {Object.entries(step.params).map(([k, v]) => `${k}=${v}`).join(", ")}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Config form from schema */}
                    {t.config_schema?.properties && Object.keys(t.config_schema.properties).length > 0 && (
                      <div className="space-y-3">
                        <h4 className="text-sm font-medium text-secondary">Configuration</h4>
                        {Object.entries(t.config_schema.properties).map(([key, prop]) => (
                          <div key={key}>
                            <label className="block text-xs mb-1 text-tertiary">
                              {prop.title || key}
                            </label>
                            {prop.type === "boolean" ? (
                              <select
                                className="input-base"
                                value={configs[t.id]?.[key] ?? prop.default ?? ""}
                                onChange={(e) => updateConfig(t.id, key, e.target.value)}
                              >
                                <option value="false">No</option>
                                <option value="true">Yes</option>
                              </select>
                            ) : (
                              <input
                                className="input-base"
                                placeholder={prop.default ?? key}
                                value={configs[t.id]?.[key] ?? prop.default ?? ""}
                                onChange={(e) => updateConfig(t.id, key, e.target.value)}
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-3 pt-2 flex-wrap">
                      <button onClick={() => runNow(t)} className="btn-primary">
                        ▶ Run Now
                      </button>
                      {(t.trigger === "scheduled" || t.trigger === "interval") && (
                        <button onClick={() => schedule(t)} className="btn-outline">
                          📅 Schedule
                        </button>
                      )}
                      <button onClick={() => openBuilder(t)} className="btn-outline">
                        🎨 Edit Steps
                      </button>
                    </div>

                    {/* Step builder panel */}
                    {showBuilder === t.id && (
                      <div className="card mt-4 p-4">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-semibold">Step Builder — {t.name}</h4>
                          <div className="flex gap-2">
                            {t.steps_goal && (
                              <button onClick={() => generateSteps(t)}
                                className="px-3 py-1 text-xs rounded transition bg-accent-muted text-accent">
                                Auto-generate
                              </button>
                            )}
                            <button onClick={addStep}
                              className="px-3 py-1 text-xs rounded transition bg-tertiary text-secondary">
                              + Add Step
                            </button>
                            <button onClick={() => saveSteps(t)}
                              className="px-3 py-1 text-xs rounded transition bg-accent-muted text-accent">
                              💾 Save
                            </button>
                            <button onClick={closeBuilder}
                              className="px-3 py-1 text-xs rounded transition bg-tertiary text-tertiary">
                              ✕
                            </button>
                          </div>
                        </div>

                        <div className="space-y-2">
                          {editSteps.length === 0 && (
                            <p className="text-xs py-4 text-center text-tertiary">
                              No steps yet. Click "+ Add Step" to start building your workflow.
                            </p>
                          )}
                          {editSteps.map((step, idx) => (
                            <div
                              key={step.uid}
                              draggable
                              onDragStart={() => onDragStart(idx)}
                              onDragOver={(e) => onDragOver(e, idx)}
                              onDrop={onDrop}
                              onDragEnd={() => { setDragIdx(null); dragOverIdx.current = null; }}
                              className="flex items-start gap-2 p-3 rounded border"
                              style={{
                                backgroundColor: "var(--dt-colors-bg-secondary)",
                                borderColor: dragIdx === idx ? "var(--dt-colors-accent-default)" : "var(--dt-colors-border-default)",
                                opacity: dragIdx === idx ? 0.5 : 1,
                              }}
                            >
                              <span className="text-xs font-medium mt-2 w-5 text-center text-tertiary">⠿</span>
                              <div className="flex-1 space-y-2">
                                <div className="flex items-center gap-2">
                                  <span className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0 bg-accent-muted text-accent">
                                    {idx + 1}
                                  </span>
                                  <input
                                    className="input-base flex-1"
                                    placeholder="Step description"
                                    value={step.description}
                                    onChange={(e) => updateStep(idx, "description", e.target.value)}
                                  />
                                  <input
                                    className="input-base"
                                    style={{ width: "7rem" }}
                                    placeholder="Tool (optional)"
                                    value={step.tool ?? ""}
                                    onChange={(e) => updateStep(idx, "tool", e.target.value || null)}
                                  />
                                  <button onClick={() => removeStep(idx)}
                                    className="text-xs px-2 py-1 rounded text-tertiary">
                                    ✕
                                  </button>
                                </div>

                                {/* Step params */}
                                <div className="flex flex-wrap gap-1 ml-7">
                                  {Object.entries(step.params).map(([k, v]) => (
                                    <div key={k} className="flex items-center gap-1">
                                      <input
                                        className="w-16 px-1.5 py-0.5 rounded border text-[10px]"
                                        style={{ backgroundColor: "var(--dt-colors-bg-primary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
                                        value={k}
                                        onChange={(e) => {
                                          const newKey = e.target.value;
                                          const val = step.params[k];
                                          removeStepParam(idx, k);
                                          updateStepParam(idx, newKey, val);
                                        }}
                                        placeholder="key"
                                      />
                                      <span className="text-[10px] text-tertiary">=</span>
                                      <input
                                        className="w-20 px-1.5 py-0.5 rounded border text-[10px]"
                                        style={{ backgroundColor: "var(--dt-colors-bg-primary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
                                        value={v}
                                        onChange={(e) => updateStepParam(idx, k, e.target.value)}
                                        placeholder="value"
                                      />
                                      <button onClick={() => removeStepParam(idx, k)}
                                        className="text-[10px] text-tertiary">
                                        ✕
                                      </button>
                                    </div>
                                  ))}
                                  <button onClick={() => addStepParam(idx)}
                                    className="text-[10px] px-1.5 py-0.5 rounded text-tertiary bg-tertiary">
                                    + param
                                  </button>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
