import { Check, ChevronLeft,ChevronRight, FileCode, FolderTree, Sparkles } from "lucide-react";
import { useEffect,useState } from "react";

import { api } from "../api/client";

interface Plan {
  id: string;
  name: string;
  description: string;
  questions: Question[];
}

interface Question {
  key: string;
  label: string;
  default: string | boolean | number;
  type: "text" | "boolean" | "select";
  options?: string[];
}

interface ScaffoldFile {
  path: string;
  content?: string;
}

interface GenerateResponse {
  files: ScaffoldFile[];
  tree: string;
}

export default function Scaffold() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [step, setStep] = useState<"select" | "configure" | "generating" | "done">("select");
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [answers, setAnswers] = useState<Record<string, string | boolean | number>>({});
  const [outputDir, setOutputDir] = useState("");
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.scaffoldPlans().then((r) => setPlans(r as Plan[]), (err) => {
      console.error("Failed to load scaffold plans:", err);
    });
  }, []);

  function startPlan(plan: Plan) {
    setSelectedPlan(plan);
    const defaults: Record<string, string | boolean | number> = {};
    for (const q of plan.questions) {
      defaults[q.key] = q.default;
    }
    setAnswers(defaults);
    setStep("configure");
  }

  async function handleGenerate() {
    if (!selectedPlan) return;
    setStep("generating");
    setError("");
    try {
      const res = await api.scaffoldGenerate(selectedPlan.id, answers, outputDir);
      setResult(res);
      setStep("done");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || "Generation failed");
      console.error("Scaffold generation failed:", err);
      setStep("configure");
    }
  }

  function reset() {
    setStep("select");
    setSelectedPlan(null);
    setResult(null);
    setError("");
    setOutputDir("");
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="page-title flex items-center gap-2 mb-6">
        <Sparkles className="w-6 h-6" style={{ color: "var(--dt-colors-accent-default)" }} />
        Project Scaffold
      </h1>

      {step === "select" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {plans.map((plan) => (
            <button key={plan.id} onClick={() => startPlan(plan)}
              className="card card-hover p-5 text-left transition-all hover:scale-[1.02]">
              <div className="flex items-start justify-between mb-2">
                <FileCode className="w-5 h-5" style={{ color: "var(--dt-colors-accent-default)" }} />
                <ChevronRight className="w-4 h-4 text-tertiary" />
              </div>
              <h3 className="font-semibold mb-1">{plan.name}</h3>
              <p className="text-xs text-tertiary">{plan.description}</p>
              <div className="mt-2 flex gap-1">
                <span className="chip">
                  {plan.questions.length} steps
                </span>
              </div>
            </button>
          ))}
          {plans.length === 0 && (
            <div className="col-span-2 text-center py-12 text-tertiary">
              Loading templates...
            </div>
          )}
        </div>
      )}

      {step === "configure" && selectedPlan && (
        <div className="card p-6">
          <div className="flex items-center gap-2 mb-1">
            <button onClick={() => setStep("select")} className="text-xs text-tertiary">
              <ChevronLeft className="w-4 h-4 inline" /> Back
            </button>
          </div>
          <h2 className="text-lg font-semibold mb-1">{selectedPlan.name}</h2>
          <p className="text-sm mb-6 text-tertiary">{selectedPlan.description}</p>

          <div className="space-y-4 mb-6">
            {selectedPlan.questions.map((q) => (
              <div key={q.key}>
                <label className="block text-sm font-medium mb-1.5">{q.label}</label>
                {q.type === "text" && (
                  <input type="text" value={String(answers[q.key] ?? "")} onChange={e => setAnswers({ ...answers, [q.key]: e.target.value })}
                    className="input-base" />
                )}
                {q.type === "boolean" && (
                  <div className="flex gap-2">
                    {[true, false].map(v => (
                      <button key={String(v)} onClick={() => setAnswers({ ...answers, [q.key]: v })}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-all"
                        style={{
                          backgroundColor: answers[q.key] === v ? "var(--dt-colors-accent-default)" : "var(--dt-colors-bg-tertiary)",
                          color: answers[q.key] === v ? "#fff" : "var(--dt-colors-text-secondary)",
                        }}>
                        {v ? "Yes" : "No"}
                      </button>
                    ))}
                  </div>
                )}
                {q.type === "select" && q.options && (
                  <div className="flex gap-2 flex-wrap">
                    {q.options.map(o => (
                      <button key={o} onClick={() => setAnswers({ ...answers, [q.key]: o })}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-all capitalize"
                        style={{
                          backgroundColor: answers[q.key] === o ? "var(--dt-colors-accent-default)" : "var(--dt-colors-bg-tertiary)",
                          color: answers[q.key] === o ? "#fff" : "var(--dt-colors-text-secondary)",
                        }}>
                        {o}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}

            <div>
              <label className="block text-sm font-medium mb-1.5">Output directory (optional)</label>
              <input type="text" value={outputDir} onChange={e => setOutputDir(e.target.value)} placeholder="e.g., projects"
                className="input-base" />
            </div>
          </div>

          {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}

          <button onClick={handleGenerate}
            className="btn-primary w-full">
            <Sparkles className="w-4 h-4" />
            Generate Project
          </button>
        </div>
      )}

      {step === "generating" && (
        <div className="flex flex-col items-center justify-center py-16 gap-4">
          <div className="w-8 h-8 border-2 rounded-full animate-spin" style={{ borderColor: "var(--dt-colors-accent-default)", borderTopColor: "transparent" }} />
          <p className="text-tertiary">Generating your project...</p>
        </div>
      )}

      {step === "done" && result && (
        <div className="space-y-6">
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-4">
              <Check className="w-5 h-5 text-success" />
              <h2 className="text-lg font-semibold">Project Generated!</h2>
            </div>
            <p className="text-sm mb-4 text-tertiary">
              {result.files?.length || 0} files created
            </p>
            <div className="mb-4">
              <h3 className="text-xs font-semibold uppercase flex items-center gap-1.5 mb-2 text-tertiary">
                <FolderTree className="w-3.5 h-3.5" /> File Tree
              </h3>
              <pre className="p-3 rounded-lg text-xs font-mono leading-relaxed overflow-x-auto" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-secondary)", border: "1px solid var(--dt-colors-border-default)" }}>
                {result.tree}
              </pre>
            </div>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {result.files?.map((f) => (
                <div key={f.path} className="flex items-center gap-2 text-xs py-1">
                  <FileCode className="w-3 h-3 shrink-0" style={{ color: "var(--dt-colors-accent-default)" }} />
                  <span className="font-mono text-secondary">{f.path}</span>
                </div>
              ))}
            </div>
          </div>
          <button onClick={reset}
            className="btn-outline">
            Create Another Project
          </button>
        </div>
      )}
    </div>
  );
}
