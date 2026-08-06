import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Bug, CheckCircle, ChevronDown, ChevronRight,FileCode, Info, RefreshCw, Search, XCircle } from "lucide-react";
import { useState } from "react";

import { api, type PatternCheckInfo, type PatternRunResponse,type PatternViolation } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";
import PageHeader from "../components/PageHeader";

export default function CodeQuality() {
  const [results, setResults] = useState<PatternRunResponse | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [activeCheck, setActiveCheck] = useState("");

  const { data: checks = [] } = useApiQuery<PatternCheckInfo[]>(["patternChecks"], () => api.patternChecks());

  const runChecks = useMutation({
    mutationFn: () => api.patternRun(undefined, activeCheck || undefined),
    onSuccess: (res) => setResults(res),
    onError: (err) => console.error("Pattern check failed", err),
  });

  const severityIcon = (sev: string) => {
    switch (sev) {
      case "error": return <XCircle className="w-3.5 h-3.5 text-danger" />;
      case "warning": return <AlertTriangle className="w-3.5 h-3.5" style={{ color: "var(--dt-colors-warning-default)" }} />;
      default: return <Info className="w-3.5 h-3.5" style={{ color: "var(--dt-colors-accent-default)" }} />;
    }
  };

  const grouped =
    results?.violations?.reduce<Record<string, PatternViolation[]>>((acc, v) => {
      (acc[v.file] ??= []).push(v);
      return acc;
    }, {}) ?? {};

  return (
    <div>
      <PageHeader
        title="Code Quality"
        subtitle="Pattern checking and convention enforcement"
        actions={
          <div className="flex items-center gap-2">
            <Bug className="w-5 h-5" style={{ color: "var(--dt-colors-accent-default)" }} />
            <button onClick={() => runChecks.mutate()} disabled={runChecks.isPending} className="btn-primary">
              <RefreshCw className={`w-4 h-4 ${runChecks.isPending ? "animate-spin" : ""}`} />
              Run Checks
            </button>
          </div>
        }
      />

      <div className="flex gap-2 flex-wrap mb-4">
        <button onClick={() => setActiveCheck("")}
          className="text-xs px-3 py-1.5 rounded-lg font-medium transition-all"
          style={{
            backgroundColor: !activeCheck ? "var(--dt-colors-accent-default)" : "var(--dt-colors-bg-tertiary)",
            color: !activeCheck ? "#fff" : "var(--dt-colors-text-secondary)",
          }}>
          All checks
        </button>
        {checks.map((c) => (
          <button key={c.id} onClick={() => setActiveCheck(c.id)}
            className="text-xs px-3 py-1.5 rounded-lg font-medium transition-all"
            style={{
              backgroundColor: activeCheck === c.id ? "var(--dt-colors-accent-default)" : "var(--dt-colors-bg-tertiary)",
              color: activeCheck === c.id ? "#fff" : "var(--dt-colors-text-secondary)",
            }}>
            {c.name}
          </button>
        ))}
      </div>

      {runChecks.isPending && (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: "var(--dt-colors-accent-default)", borderTopColor: "transparent" }} />
          <span className="ml-3 text-sm text-tertiary">Scanning project...</span>
        </div>
      )}

      {results && !runChecks.isPending && (
        <>
          <div className="flex gap-3 mb-6">
            {[
              { label: "Files", value: results.files_checked, color: "var(--dt-colors-text-primary)" },
              { label: "Errors", value: results.by_severity?.error || 0, color: "var(--dt-colors-danger-default)" },
              { label: "Warnings", value: results.by_severity?.warning || 0, color: "var(--dt-colors-warning-default)" },
              { label: "Info", value: results.by_severity?.info || 0, color: "var(--dt-colors-accent-default)" },
            ].map((s) => (
              <div key={s.label} className="stat-card flex-1 text-center">
                <div className="stat-card-value" style={{ color: s.color }}>{s.value}</div>
                <div className="stat-card-label">{s.label}</div>
              </div>
            ))}
          </div>

          {Object.keys(grouped).length === 0 ? (
            <div className="text-center py-12 text-tertiary">
              <CheckCircle className="w-10 h-10 mx-auto mb-3 text-success" />
              <p className="text-sm font-medium">No violations found!</p>
              <p className="text-xs mt-1">All checked files follow the conventions.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(grouped).map(([file, violations]) => {
                const isOpen = expanded[file];
                return (
                  <div key={file} className="card overflow-hidden">
                    <button onClick={() => setExpanded({ ...expanded, [file]: !isOpen })}
                      className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium"
                      style={{ borderBottom: isOpen ? "1px solid var(--dt-colors-border-default)" : "none" }}>
                      {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                      <FileCode className="w-4 h-4" style={{ color: "var(--dt-colors-accent-default)" }} />
                      <span className="flex-1 truncate font-mono text-xs">{file}</span>
                      <div className="flex gap-1.5 text-xs">
                        <span className="badge badge-error">
                          {violations.filter((v) => v.severity === "error").length}E
                        </span>
                        <span className="badge badge-warning">
                          {violations.filter((v) => v.severity === "warning").length}W
                        </span>
                        <span className="badge badge-accent">
                          {violations.filter((v) => v.severity === "info").length}I
                        </span>
                      </div>
                    </button>
                    {isOpen && (
                      <div className="divide-y border-default">
                        {violations.map((v, i) => (
                          <div key={i} className="px-4 py-2.5 text-sm">
                            <div className="flex items-start gap-2">
                              <div className="mt-0.5">{severityIcon(v.severity)}</div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-0.5">
                                  <span className="text-xs font-medium capitalize text-tertiary">
                                    L{v.line}
                                  </span>
                                  <span className={`badge ${v.severity === "error" ? "badge-error" : v.severity === "warning" ? "badge-warning" : "badge-accent"}`}>
                                    {v.severity}
                                  </span>
                                </div>
                                <p className="text-primary">{v.message}</p>
                                <pre className="mt-1 text-xs font-mono px-2 py-1 rounded overflow-x-auto" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-tertiary)" }}>
                                  {v.line_content}
                                </pre>
                                <p className="mt-1 text-xs text-tertiary">
                                  💡 {v.fix_hint}
                                </p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {!results && !runChecks.isPending && (
        <div className="text-center py-16 text-tertiary">
          <Search className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Click "Run Checks" to scan your project for pattern violations</p>
          <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-xl mx-auto">
            {checks.map((c) => (
              <div key={c.id} className="rounded-lg p-3 text-left text-xs bg-tertiary">
                <div className="font-medium mb-0.5">{c.name}</div>
                <div className="text-tertiary">{c.severity}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
