import { useState } from "react";
import { api } from "../api/client";

export default function Tests() {
  const [path, setPath] = useState("");
  const [marker, setMarker] = useState("");
  const [timeout, setTimeout_] = useState("120");
  const [extraArgs, setExtraArgs] = useState("");
  const [filePath, setFilePath] = useState("");
  const [result, setResult] = useState("");
  const [tab, setTab] = useState<"run" | "coverage" | "generate">("run");
  const [loading, setLoading] = useState(false);

  async function handleRun() {
    setLoading(true);
    setResult("");
    try {
      const r = await api.testsRun(path, marker, parseInt(timeout) || 120, extraArgs);
      setResult(r.text);
    } catch (e: any) {
      setResult(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleCoverage() {
    setLoading(true);
    setResult("");
    try {
      const r = await api.testsCoverage(path, parseInt(timeout) || 180);
      setResult(r.text);
    } catch (e: any) {
      setResult(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    if (!filePath) return;
    setLoading(true);
    setResult("");
    try {
      const r = await api.testsGenerate(filePath);
      setResult(r.text);
    } catch (e: any) {
      setResult(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Tests</h1>

      <div className="flex gap-1 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        {(["run", "coverage", "generate"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "border-b-2" : ""}`}
            style={{
              color: tab === t ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)",
              borderColor: tab === t ? "var(--dt-colors-accent-default)" : "transparent",
            }}>
            {t === "run" ? "Run Tests" : t === "coverage" ? "Coverage" : "Generate"}
          </button>
        ))}
      </div>

      {tab === "run" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Path (optional, defaults to current dir)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Marker filter (e.g. 'not slow')"
            value={marker}
            onChange={(e) => setMarker(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <input
              className="px-3 py-2 rounded border text-sm w-24"
              style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
              placeholder="Timeout"
              type="number"
              value={timeout}
              onChange={(e) => setTimeout_(e.target.value)}
            />
            <input
              className="flex-1 px-3 py-2 rounded border text-sm"
              style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
              placeholder="Extra pytest args"
              value={extraArgs}
              onChange={(e) => setExtraArgs(e.target.value)}
            />
          </div>
          <button onClick={handleRun} disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            {loading ? "Running..." : "Run Tests"}
          </button>
        </div>
      )}

      {tab === "coverage" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Path (optional)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <input
            className="px-3 py-2 rounded border text-sm w-24"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Timeout"
            type="number"
            value={timeout}
            onChange={(e) => setTimeout_(e.target.value)}
          />
          <button onClick={handleCoverage} disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            {loading ? "Running..." : "Measure Coverage"}
          </button>
        </div>
      )}

      {tab === "generate" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ backgroundColor: "var(--dt-colors-bg-secondary)", borderColor: "var(--dt-colors-border-default)", color: "var(--dt-colors-text-primary)" }}
            placeholder="Path to Python source file"
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
          />
          <button onClick={handleGenerate} disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium transition"
            style={{ backgroundColor: "var(--dt-colors-accent-muted)", color: "var(--dt-colors-accent-default)" }}>
            {loading ? "Generating..." : "Generate Tests"}
          </button>
        </div>
      )}

      {result && (
        <pre className="p-4 rounded text-sm whitespace-pre-wrap"
          style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-primary)" }}>
          {result}
        </pre>
      )}
    </div>
  );
}
