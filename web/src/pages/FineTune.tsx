import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

interface DatasetStats {
  conversations?: number;
  code_samples?: number;
  config?: { max_length?: number };
}

interface ModelInfo {
  model_name?: string;
  model_type?: string;
  trainable_params?: number;
  total_params?: number;
}

interface Checkpoint {
  step?: number;
  epoch?: number;
  path?: string;
}

interface TrainingResult {
  train_loss?: number;
  global_step?: number;
  epoch?: number;
  eval_loss?: number;
  eval_perplexity?: number;
}

type Tab = "dataset" | "model" | "training";

export default function FineTune() {
  const [tab, setTab] = useState<Tab>("dataset");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [datasetStats, setDatasetStats] = useState<DatasetStats | null>(null);
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);

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
  const [trainingResult, setTrainingResult] = useState<TrainingResult | null>(null);

  const loadDatasetStatsMutation = useMutation({
    mutationFn: () => api.finetuneDatasetStats(),
    onSuccess: (r) => { setDatasetStats(r); setError(""); },
    onError: (e: any) => setError(e.message),
  });

  const addConversationMutation = useMutation({
    mutationFn: () => api.finetuneAddConversation(systemPrompt, messagesJson),
    onSuccess: (r) => {
      setMsg(`Conversation added. Total: ${r.total}`); setError("");
      setSystemPrompt(""); setMessagesJson("");
      loadDatasetStatsMutation.mutate();
    },
    onError: (e: any) => setError(e.message),
  });

  const addCodeMutation = useMutation({
    mutationFn: () => api.finetuneAddCode(code, codeLang),
    onSuccess: (r) => {
      setMsg(`Code sample added. Total: ${r.total}`); setError("");
      setCode(""); setCodeLang("");
      loadDatasetStatsMutation.mutate();
    },
    onError: (e: any) => setError(e.message),
  });

  const loadModelMutation = useMutation({
    mutationFn: () => api.finetuneLoadModel(modelType, useLora, useQlora),
    onSuccess: (r) => { setModelInfo(r); setMsg(`Model loaded: ${r.model_name}`); setError(""); },
    onError: (e: any) => setError(e.message),
  });

  const startTrainingMutation = useMutation({
    mutationFn: () => api.finetuneStartTraining(epochs, parseFloat(lr), batchSize),
    onSuccess: (r) => {
      setTrainingResult(r); setMsg(`Training completed! Loss: ${r.train_loss?.toFixed(4)}`); setError("");
    },
    onError: (e: any) => setError(e.message),
  });

  const loadCheckpointsMutation = useMutation({
    mutationFn: () => api.finetuneCheckpoints(),
    onSuccess: (r) => { setCheckpoints(r.checkpoints); setError(""); },
    onError: (e: any) => setError(e.message),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "dataset", label: "Dataset" },
    { key: "model", label: "Model" },
    { key: "training", label: "Training" },
  ];

  return (
    <div>
      <PageHeader title="Fine-Tuning" subtitle="Prepare datasets, load models, and run training" />
      <div className="flex gap-1 mb-6 border-b border-default">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition ${tab === t.key ? "tab-active" : "tab-inactive"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {tab === "dataset" && (
        <div className="space-y-6">
          <div className="card p-4">
            <h2 className="text-lg font-semibold mb-3">Add Conversation</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="System prompt" value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)}
                className="input-base" />
              <textarea placeholder='[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]' value={messagesJson} onChange={e => setMessagesJson(e.target.value)}
                rows={4} className="input-base font-mono" />
            </div>
            <button onClick={() => addConversationMutation.mutate()} disabled={addConversationMutation.isPending}
              className="btn-primary">
              {addConversationMutation.isPending ? "Adding..." : "Add Conversation"}
            </button>
          </div>

          <div className="card p-4">
            <h2 className="text-lg font-semibold mb-3">Add Code Sample</h2>
            <div className="space-y-3 mb-3">
              <input placeholder="Language (python, javascript, ...)" value={codeLang} onChange={e => setCodeLang(e.target.value)}
                className="input-base" />
              <textarea placeholder="Source code..." value={code} onChange={e => setCode(e.target.value)}
                rows={6} className="input-base font-mono" />
            </div>
            <button onClick={() => addCodeMutation.mutate()} disabled={addCodeMutation.isPending || !code}
              className="btn-primary">
              {addCodeMutation.isPending ? "Adding..." : "Add Code"}
            </button>
          </div>

          <div className="card p-4">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Dataset Statistics</h2>
              <button onClick={() => loadDatasetStatsMutation.mutate()} className="px-3 py-1 rounded-lg text-xs btn-secondary-text">
                Refresh
              </button>
            </div>
            {datasetStats ? (
              <div className="grid grid-cols-3 gap-3">
                <div className="stat-card text-center">
                  <div className="stat-card-label">Conversations</div>
                  <div className="stat-card-value">{datasetStats.conversations}</div>
                </div>
                <div className="stat-card text-center">
                  <div className="stat-card-label">Code Samples</div>
                  <div className="stat-card-value">{datasetStats.code_samples}</div>
                </div>
                <div className="stat-card text-center">
                  <div className="stat-card-label">Max Length</div>
                  <div className="stat-card-value">{datasetStats.config?.max_length}</div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-tertiary">Click Refresh to load stats.</p>
            )}
          </div>
        </div>
      )}

      {tab === "model" && (
        <div className="space-y-6">
          <div className="card p-4">
            <h2 className="text-lg font-semibold mb-3">Load Model</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <select value={modelType} onChange={e => setModelType(e.target.value)}
                className="input-base">
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
            <button onClick={() => loadModelMutation.mutate()} disabled={loadModelMutation.isPending}
              className="btn-primary">
              {loadModelMutation.isPending ? "Loading..." : "Load Model"}
            </button>
            {modelInfo && (
              <div className="mt-3 p-3 rounded-lg bg-tertiary">
                <p>Model: {modelInfo.model_name}</p>
                <p>Type: {modelInfo.model_type}</p>
                <p>Trainable params: {modelInfo.trainable_params?.toLocaleString()}</p>
                <p>Total params: {modelInfo.total_params?.toLocaleString()}</p>
              </div>
            )}
          </div>

          <div className="card p-4">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-lg font-semibold">Checkpoints</h2>
              <button onClick={() => loadCheckpointsMutation.mutate()} className="px-3 py-1 rounded-lg text-xs btn-secondary-text">
                Refresh
              </button>
            </div>
            {checkpoints.length === 0 ? (
              <p className="text-sm text-tertiary">No checkpoints yet.</p>
            ) : (
              <div className="space-y-2">
                {checkpoints.map((cp, i) => (
                  <div key={i} className="p-2 rounded-lg text-sm bg-tertiary">
                    step={cp.step}, epoch={cp.epoch}, path={cp.path}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "training" && (
        <div className="card p-4">
          <h2 className="text-lg font-semibold mb-3">Start Training</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-xs text-tertiary">Epochs</label>
              <input type="number" min={1} max={100} value={epochs} onChange={e => setEpochs(parseInt(e.target.value) || 3)}
                className="input-base mt-1" />
            </div>
            <div>
              <label className="text-xs text-tertiary">Learning Rate</label>
              <input value={lr} onChange={e => setLr(e.target.value)}
                className="input-base mt-1" />
            </div>
            <div>
              <label className="text-xs text-tertiary">Batch Size</label>
              <input type="number" min={1} max={128} value={batchSize} onChange={e => setBatchSize(parseInt(e.target.value) || 4)}
                className="input-base mt-1" />
            </div>
          </div>
          <button onClick={() => startTrainingMutation.mutate()} disabled={startTrainingMutation.isPending}
            className="btn-primary">
            {startTrainingMutation.isPending ? "Training..." : "Start Training"}
          </button>
          {trainingResult && (
            <div className="mt-3 p-3 rounded-lg bg-tertiary">
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
