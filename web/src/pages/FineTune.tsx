import { useState } from "react";
import { api } from "../api/client";

type Tab = "dataset" | "model" | "training";

export default function FineTune() {
  const [tab, setTab] = useState<Tab>("dataset");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [datasetStats, setDatasetStats] = useState<any>(null);
  const [modelInfo, setModelInfo] = useState<any>(null);
  const [checkpoints, setCheckpoints] = useState<any[]>([]);

  // dataset
  const [systemPrompt, setSystemPrompt] = useState("");
  const [messagesJson, setMessagesJson] = useState("");
  const [code, setCode] = useState("");
  const [codeLang, setCodeLang] = useState("");

  // model
  const [modelType, setModelType] = useState("llama");
  const [useLora, setUseLora] = useState(true);
  const [useQlora, setUseQlora] = useState(false);

  // training
  const [epochs, setEpochs] = useState(3);
  const [lr, setLr] = useState("2e-4");
  const [batchSize, setBatchSize] = useState(4);
  const [trainingResult, setTrainingResult] = useState<any>(null);

  async function loadDatasetStats() {
    setLoading(true); setError("");
    try {
      const r = await api.finetuneDatasetStats();
      setDatasetStats(r);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleAddConversation() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.finetuneAddConversation(systemPrompt, messagesJson);
      setMsg(`Conversation added. Total: ${r.total}`);
      setSystemPrompt(""); setMessagesJson("");
      loadDatasetStats();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleAddCode() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.finetuneAddCode(code, codeLang);
      setMsg(`Code sample added. Total: ${r.total}`);
      setCode(""); setCodeLang("");
      loadDatasetStats();
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleLoadModel() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r = await api.finetuneLoadModel(modelType, useLora, useQlora);
      setModelInfo(r);
      setMsg(`Model loaded: ${r.model_name}`);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function handleStartTraining() {
    setTrainingResult(null); setMsg(""); setError("");
    setLoading(true);
    try {
      const r = await api.finetuneStartTraining(epochs, parseFloat(lr), batchSize);
      setTrainingResult(r);
      setMsg(`Training completed! Loss: ${r.train_loss?.toFixed(4)}`);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  async function loadCheckpoints() {
    setLoading(true); setError("");
    try {
      const r = await api.finetuneCheckpoints();
      setCheckpoints(r.checkpoints);
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "dataset", label: "Dataset" },
    { key: "model", label: "Model" },
    { key: "training", label: "Training" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Fine-Tuning</h1>
      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
            style={{ color: tab === t.key ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === t.key ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {tab === "dataset" && (
        <div className="space-y-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Add Conversation</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="System prompt" value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <textarea placeholder='[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]' value={messagesJson} onChange={e => setMessagesJson(e.target.value)}
                rows={4} className="w-full px-3 py-2 rounded-lg text-sm font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <button onClick={handleAddConversation} disabled={loading}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              Add Conversation
            </button>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Add Code Sample</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="Language (python, javascript, ...)" value={codeLang} onChange={e => setCodeLang(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              <textarea placeholder="Source code..." value={code} onChange={e => setCode(e.target.value)}
                rows={6} className="w-full px-3 py-2 rounded-lg text-sm font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <button onClick={handleAddCode} disabled={loading || !code}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              Add Code
            </button>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Dataset Statistics</h2>
              <button onClick={loadDatasetStats} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
                Refresh
              </button>
            </div>
            {datasetStats ? (
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-2xl font-bold">{datasetStats.conversations}</div>
                  <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Conversations</div>
                </div>
                <div className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-2xl font-bold">{datasetStats.code_samples}</div>
                  <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Code Samples</div>
                </div>
                <div className="p-3 rounded-lg text-center" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <div className="text-2xl font-bold">{datasetStats.config?.max_length}</div>
                  <div className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Max Length</div>
                </div>
              </div>
            ) : (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>Click Refresh to load stats.</p>
            )}
          </div>
        </div>
      )}

      {tab === "model" && (
        <div className="space-y-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Load Model</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <select value={modelType} onChange={e => setModelType(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }}>
                <option value="llama">Llama</option>
                <option value="mistral">Mistral</option>
                <option value="falcon">Falcon</option>
                <option value="phi">Phi</option>
                <option value="qwen">Qwen</option>
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={useLora} onChange={e => setUseLora(e.target.checked)} />
                LoRA
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={useQlora} onChange={e => setUseQlora(e.target.checked)} />
                QLoRA
              </label>
            </div>
            <button onClick={handleLoadModel} disabled={loading}
              className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
              {loading ? "Loading..." : "Load Model"}
            </button>
            {modelInfo && (
              <div className="mt-3 p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                <p>Model: {modelInfo.model_name}</p>
                <p>Type: {modelInfo.model_type}</p>
                <p>Trainable params: {modelInfo.trainable_params?.toLocaleString()}</p>
                <p>Total params: {modelInfo.total_params?.toLocaleString()}</p>
              </div>
            )}
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Checkpoints</h2>
              <button onClick={loadCheckpoints} className="px-3 py-1 rounded-lg text-xs" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-secondary)" }}>
                Refresh
              </button>
            </div>
            {checkpoints.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No checkpoints yet.</p>
            ) : (
              <div className="space-y-2">
                {checkpoints.map((cp, i) => (
                  <div key={i} className="p-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    step={cp.step}, epoch={cp.epoch}, path={cp.path}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "training" && (
        <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
          <h2 className="text-lg font-semibold mb-3">Start Training</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Epochs</label>
              <input type="number" min={1} max={100} value={epochs} onChange={e => setEpochs(parseInt(e.target.value) || 3)}
                className="w-full px-3 py-2 rounded-lg text-sm mt-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <div>
              <label className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Learning Rate</label>
              <input value={lr} onChange={e => setLr(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm mt-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
            <div>
              <label className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>Batch Size</label>
              <input type="number" min={1} max={128} value={batchSize} onChange={e => setBatchSize(parseInt(e.target.value) || 4)}
                className="w-full px-3 py-2 rounded-lg text-sm mt-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
            </div>
          </div>
          <button onClick={handleStartTraining} disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
            {loading ? "Training..." : "Start Training"}
          </button>
          {trainingResult && (
            <div className="mt-3 p-3 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
              <h3 className="font-semibold mb-2">Training Results</h3>
              <p>Train Loss: {trainingResult.train_loss?.toFixed(4)}</p>
              <p>Global Step: {trainingResult.global_step}</p>
              <p>Epoch: {trainingResult.epoch}</p>
              {trainingResult.eval_loss != null && <p>Eval Loss: {trainingResult.eval_loss?.toFixed(4)}</p>}
              {trainingResult.eval_perplexity != null && <p>Perplexity: {trainingResult.eval_perplexity?.toFixed(4)}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
