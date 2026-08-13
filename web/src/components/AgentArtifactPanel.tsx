import { useState } from "react";
import { Check, Copy, FileCode2, FileText, Image as ImageIcon, PanelRightClose, PanelRightOpen, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

import type { AgentArtifact } from "../hooks/useAgentSocket";

function artifactIcon(type: string) {
  switch (type) {
    case "mermaid":
    case "svg":
      return <ImageIcon className="h-4 w-4" />;
    case "markdown":
      return <FileText className="h-4 w-4" />;
    default:
      return <FileCode2 className="h-4 w-4" />;
  }
}

function ArtifactBody({ artifact }: { artifact: AgentArtifact }) {
  const type = artifact.type || "code";

  if (type === "markdown") {
    return (
      <div className="text-sm leading-relaxed prose prose-invert max-w-none">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{artifact.content}</ReactMarkdown>
      </div>
    );
  }

  if (type === "html" || type === "svg") {
    return (
      <iframe
        sandbox="allow-scripts"
        srcDoc={artifact.content}
        title={artifact.title}
        className="h-64 w-full rounded border border-default bg-white"
      />
    );
  }

  if (type === "mermaid") {
    return (
      <div className="text-xs text-secondary">
        <p className="mb-2">Диаграмма: подключите Mermaid-рендер для живого превью. Исходник:</p>
        <pre className="whitespace-pre-wrap rounded border border-default bg-tertiary p-2 font-mono text-xs text-secondary">
          {artifact.content}
        </pre>
      </div>
    );
  }

  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-default bg-tertiary p-2 font-mono text-xs text-primary">
      {artifact.content}
    </pre>
  );
}

function ArtifactCard({ artifact }: { artifact: AgentArtifact }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(artifact.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-default bg-secondary">
      <div className="flex items-center gap-2 border-b border-default bg-tertiary px-3 py-2 text-xs">
        <span className="text-accent">{artifactIcon(artifact.type)}</span>
        <span className="truncate font-medium text-primary">{artifact.title || "Artifact"}</span>
        <span className="rounded bg-tertiary px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-secondary border border-default">
          {artifact.type || "code"}
        </span>
        {artifact.file_path && (
          <span className="truncate font-mono text-[10px] text-tertiary">{artifact.file_path}</span>
        )}
        <button
          type="button"
          onClick={copy}
          className="ml-auto flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-secondary transition-opacity hover:opacity-70"
          aria-label="Copy artifact content"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="p-3">
        <ArtifactBody artifact={artifact} />
      </div>
    </div>
  );
}

export default function AgentArtifactPanel({
  artifacts,
  open,
  onToggle,
  onClear,
}: {
  artifacts: AgentArtifact[];
  open: boolean;
  onToggle: () => void;
  onClear: () => void;
}) {
  return (
    <aside
      className={`flex flex-col transition-all duration-200 ${
        open ? "w-[420px] min-w-[420px]" : "w-12 min-w-12"
      } border-l border-default bg-tertiary`}
    >
      <div className="flex items-center justify-between border-b border-default px-3 py-2">
        {open && <span className="text-sm font-semibold text-primary">Artifacts ({artifacts.length})</span>}
        <div className="flex items-center gap-1">
          {open && artifacts.length > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="rounded p-1.5 text-secondary transition-colors hover:bg-secondary hover:text-primary"
              aria-label="Clear artifacts"
              title="Clear artifacts"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={onToggle}
            className="rounded p-1.5 text-secondary transition-colors hover:bg-secondary hover:text-primary"
            aria-label={open ? "Hide artifacts" : "Show artifacts"}
            title={open ? "Hide artifacts" : "Show artifacts"}
          >
            {open ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
          </button>
        </div>
      </div>
      {open && (
        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {artifacts.length === 0 && (
            <p className="py-8 text-center text-sm text-tertiary">
              Артефакты появятся здесь, когда агент вызовет create_artifact
            </p>
          )}
          {artifacts.map((a) => (
            <ArtifactCard key={a.artifact_id || `${a.title}-${a.step}`} artifact={a} />
          ))}
        </div>
      )}
    </aside>
  );
}
