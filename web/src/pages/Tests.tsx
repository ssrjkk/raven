import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

export default function Tests() {
  const [path, setPath] = useState("");
  const [marker, setMarker] = useState("");
  const [timeout, setTimeout_] = useState("120");
  const [extraArgs, setExtraArgs] = useState("");
  const [filePath, setFilePath] = useState("");
  const [result, setResult] = useState("");
  const [tab, setTab] = useState<"run" | "coverage" | "generate">("run");

  const runTests = useMutation({
    mutationFn: () => api.testsRun(path, marker, parseInt(timeout) || 120, extraArgs),
    onSuccess: (r) => setResult(r.text),
    onError: (e: any) => setResult(`Error: ${e.message}`),
  });

  const measureCoverage = useMutation({
    mutationFn: () => api.testsCoverage(path, parseInt(timeout) || 180),
    onSuccess: (r) => setResult(r.text),
    onError: (e: any) => setResult(`Error: ${e.message}`),
  });

  const generateTests = useMutation({
    mutationFn: () => api.testsGenerate(filePath),
    onSuccess: (r) => setResult(r.text),
    onError: (e: any) => setResult(`Error: ${e.message}`),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Tests" subtitle="Run pytest suites, measure coverage, and generate tests" />

      <div className="flex gap-1 border-b border-default">
        {(["run", "coverage", "generate"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition rounded-t ${tab === t ? "tab-active" : "tab-inactive"}`}>
            {t === "run" ? "Run Tests" : t === "coverage" ? "Coverage" : "Generate"}
          </button>
        ))}
      </div>

      {tab === "run" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="input-base"
            placeholder="Path (optional, defaults to current dir)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <input
            className="input-base"
            placeholder="Marker filter (e.g. 'not slow')"
            value={marker}
            onChange={(e) => setMarker(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <input
              className="input-base"
              style={{ width: "6rem" }}
              placeholder="Timeout"
              type="number"
              value={timeout}
              onChange={(e) => setTimeout_(e.target.value)}
            />
            <input
              className="input-base flex-1"
              placeholder="Extra pytest args"
              value={extraArgs}
              onChange={(e) => setExtraArgs(e.target.value)}
            />
          </div>
          <button onClick={() => runTests.mutate()} disabled={runTests.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            {runTests.isPending ? "Running..." : "Run Tests"}
          </button>
        </div>
      )}

      {tab === "coverage" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="input-base"
            placeholder="Path (optional)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <input
            className="input-base"
            style={{ width: "6rem" }}
            placeholder="Timeout"
            type="number"
            value={timeout}
            onChange={(e) => setTimeout_(e.target.value)}
          />
          <button onClick={() => measureCoverage.mutate()} disabled={measureCoverage.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            {measureCoverage.isPending ? "Running..." : "Measure Coverage"}
          </button>
        </div>
      )}

      {tab === "generate" && (
        <div className="space-y-3 max-w-lg">
          <input
            className="input-base"
            placeholder="Path to Python source file"
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && generateTests.mutate()}
          />
          <button onClick={() => generateTests.mutate()} disabled={generateTests.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent-muted text-accent">
            {generateTests.isPending ? "Generating..." : "Generate Tests"}
          </button>
        </div>
      )}

      {result && (
        <pre className="p-4 rounded text-sm whitespace-pre-wrap bg-secondary text-primary">
          {result}
        </pre>
      )}
    </div>
  );
}
