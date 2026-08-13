import { useCallback, useRef, useState } from "react";
import { Bot, CheckCircle2, Loader2, SendHorizontal, Terminal, XCircle } from "lucide-react";

import AgentArtifactPanel from "../components/AgentArtifactPanel";
import PageHeader from "../components/PageHeader";
import { type AgentArtifact, type AgentSocketEvent, useAgentSocket } from "../hooks/useAgentSocket";

interface TraceRow {
  id: number;
  kind: string;
  step?: number;
  name?: string;
  text: string;
}

function formatArgs(args: unknown): string {
  if (typeof args === "string") return args;
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function traceTitle(kind: string): string {
  switch (kind) {
    case "user":
      return "Prompt";
    case "message":
      return "Message";
    case "tool_call":
      return "Tool call";
    case "tool_result":
      return "Tool result";
    case "done":
      return "Done";
    case "error":
      return "Error";
    default:
      return kind;
  }
}

function TraceIcon({ kind }: { kind: string }) {
  if (kind === "error") return <XCircle className="h-4 w-4 text-red-400" />;
  if (kind === "done") return <CheckCircle2 className="h-4 w-4 text-green-400" />;
  if (kind === "tool_call" || kind === "tool_result") return <Terminal className="h-4 w-4 text-accent" />;
  return <Bot className="h-4 w-4 text-secondary" />;
}

export default function AgentConsole() {
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [panelOpen, setPanelOpen] = useState(true);
  const [input, setInput] = useState("");
  const traceId = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const onEvent = useCallback((ev: AgentSocketEvent) => {
    const d = ev.data as Record<string, unknown>;
    const step = typeof d.step === "number" ? d.step : undefined;

    if (ev.type === "artifact_created") {
      const artifact: AgentArtifact = {
        artifact_id: String(d.artifact_id ?? ""),
        title: String(d.title ?? "Artifact"),
        type: String(d.type ?? "code"),
        file_path: typeof d.file_path === "string" ? d.file_path : null,
        content: String(d.content ?? ""),
        step: step ?? 0,
      };
      setArtifacts((prev) => {
        const idx = prev.findIndex((a) => a.artifact_id && a.artifact_id === artifact.artifact_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = artifact;
          return next;
        }
        return [...prev, artifact];
      });
      return;
    }

    let text = "";
    if (ev.type === "tool_call") {
      text = `${String(d.name ?? "tool")}(${formatArgs(d.args)})`;
    } else if (ev.type === "tool_result") {
      const result = String(d.result ?? "");
      text = `${String(d.name ?? "tool")} → ${result.length > 2000 ? `${result.slice(0, 2000)}… (truncated)` : result}`;
    } else if (ev.type === "message") {
      text = String(d.content ?? "");
    } else if (ev.type === "step_start") {
      text = `Step ${String(d.step ?? "")} — ${String(d.goal ?? "")}`;
    } else if (ev.type === "done") {
      text = `Finished in ${String(d.steps ?? "")} steps: ${String(d.reason ?? "")}`;
    } else if (ev.type === "error") {
      text = String(d.message ?? String(d.detail ?? "unknown error"));
    } else {
      text = JSON.stringify(d);
    }

    traceId.current += 1;
    setTraces((prev) => [...prev, { id: traceId.current, kind: ev.type, step, name: ev.type === "tool_call" || ev.type === "tool_result" ? String(d.name ?? "") : undefined, text }]);
  }, []);

  const { connected, running, send } = useAgentSocket(onEvent);

  const run = () => {
    const prompt = input.trim();
    if (!prompt || running) return;
    setInput("");
    traceId.current += 1;
    setTraces((prev) => [...prev, { id: traceId.current, kind: "user", text: prompt }]);
    send(prompt);
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  const clear = () => {
    setTraces([]);
    setArtifacts([]);
  };

  const status = !connected ? "disconnected" : running ? "running" : "idle";

  return (
    <div className="flex h-[calc(100vh-140px)] min-h-[480px] flex-col gap-4">
      <PageHeader
        title="Agent Console"
        subtitle="Live /ws/agent session — stream tool calls and artifacts in real time"
        icon={Bot}
        actions={
          <div className="flex items-center gap-2">
            <span className="badge badge-info flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`} />
              {status}
            </span>
            <button type="button" className="btn-secondary" onClick={clear}>
              Clear
            </button>
          </div>
        }
      />

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex min-w-0 flex-1 flex-col rounded-xl border border-default bg-secondary">
          <div className="flex items-center gap-2 border-b border-default bg-tertiary px-3 py-2 text-sm font-medium text-primary">
            <Terminal className="h-4 w-4 text-accent" />
            Trace
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {traces.length === 0 && (
              <p className="py-8 text-center text-sm text-tertiary">
                Отправьте промпт — сюда будут стримиться события step/tool/message
              </p>
            )}
            {traces.map((t) => (
              <div key={t.id} className="rounded-lg border border-default bg-tertiary p-2.5">
                <div className="mb-1 flex items-center gap-2 text-[11px] text-secondary">
                  <TraceIcon kind={t.kind} />
                  <span className="font-medium uppercase tracking-wider">{traceTitle(t.kind)}</span>
                  {t.step !== undefined && <span className="text-tertiary">step {t.step}</span>}
                  {t.name && <span className="font-mono text-accent">{t.name}</span>}
                </div>
                <pre className="whitespace-pre-wrap font-mono text-xs text-primary">{t.text}</pre>
              </div>
            ))}
            {running && (
              <div className="flex items-center gap-2 px-1 text-sm text-secondary">
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
                Agent is working…
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <AgentArtifactPanel artifacts={artifacts} open={panelOpen} onToggle={() => setPanelOpen((p) => !p)} onClear={() => setArtifacts([])} />
      </div>

      <form
        className="flex shrink-0 gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              run();
            }
          }}
          placeholder="Describe a task for the autonomous agent… (Enter to run, Shift+Enter for newline)"
          className="input-base flex-1 resize-none"
          rows={2}
        />
        <button type="submit" disabled={!connected || running} className="btn-primary flex items-center gap-2">
          <SendHorizontal className="h-4 w-4" />
          Run
        </button>
      </form>
    </div>
  );
}
