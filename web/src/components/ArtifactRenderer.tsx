import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { Check, Code2, Copy, FileText, Image } from "lucide-react";

export interface ArtifactPayload {
  artifact_id: string;
  title?: string;
  type?: string;
  content: string;
  file_path?: string | null;
}

interface ExtractedArtifact {
  payload: ArtifactPayload;
  text: string;
}

function extractArtifacts(text: string): ExtractedArtifact[] {
  const out: ExtractedArtifact[] = [];
  let rest = text;
  const startMarker = '{"artifact_id"';
  while (true) {
    const idx = rest.indexOf(startMarker);
    if (idx === -1) break;
    const before = rest.slice(0, idx);
    const after = rest.slice(idx);
    let depth = 0;
    let inStr = false;
    let esc = false;
    let end = -1;
    for (let i = 0; i < after.length; i++) {
      const ch = after[i];
      if (inStr) {
        if (esc) esc = false;
        else if (ch === "\\") esc = true;
        else if (ch === '"') inStr = false;
      } else if (ch === '"') {
        inStr = true;
      } else if (ch === "{") {
        depth++;
      } else if (ch === "}") {
        depth--;
        if (depth === 0) {
          end = i + 1;
          break;
        }
      }
    }
    if (end === -1) break;
    const jsonText = after.slice(0, end);
    try {
      const payload = JSON.parse(jsonText) as ArtifactPayload;
      if (payload.artifact_id && typeof payload.content === "string") {
        out.push({ payload, text: before });
        rest = after.slice(end);
        continue;
      }
    } catch {
      // not a valid artifact JSON — keep scanning
    }
    rest = after.slice(1);
  }
  if (out.length === 0) return [];
  out[out.length - 1].text += rest;
  return out;
}

function artifactIcon(type: string | undefined) {
  switch (type) {
    case "mermaid":
    case "svg":
      return <Image className="h-4 w-4" />;
    case "markdown":
      return <FileText className="h-4 w-4" />;
    default:
      return <Code2 className="h-4 w-4" />;
  }
}

function ArtifactCard({ artifact }: { artifact: ArtifactPayload }) {
  const [copied, setCopied] = useState(false);
  const type = artifact.type || "code";

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
    <div
      className="rounded-xl overflow-hidden my-2 text-left"
      style={{
        border: "1px solid var(--dt-colors-border-default)",
        backgroundColor: "var(--dt-colors-bg-secondary)",
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2 text-xs"
        style={{
          backgroundColor: "var(--dt-colors-bg-tertiary)",
          borderBottom: "1px solid var(--dt-colors-border-default)",
        }}
      >
        <span style={{ color: "var(--dt-colors-accent-default)" }}>{artifactIcon(type)}</span>
        <span className="font-medium" style={{ color: "var(--dt-colors-text-primary)" }}>
          {artifact.title || "Artifact"}
        </span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider"
          style={{
            color: "var(--dt-colors-text-secondary)",
            backgroundColor: "var(--dt-colors-bg-tertiary)",
            border: "1px solid var(--dt-colors-border-default)",
          }}
        >
          {type}
        </span>
        {artifact.file_path && (
          <span className="font-mono text-[10px] opacity-60 truncate">{artifact.file_path}</span>
        )}
        <button
          type="button"
          onClick={copy}
          className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-opacity hover:opacity-70"
          style={{ color: "var(--dt-colors-text-secondary)" }}
          aria-label="Copy artifact content"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="p-3">
        {type === "markdown" ? (
          <div className="text-sm leading-relaxed prose prose-invert max-w-none">
            <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{artifact.content}</ReactMarkdown>
          </div>
        ) : type === "mermaid" ? (
          <div className="text-xs" style={{ color: "var(--dt-colors-text-secondary)" }}>
            <p className="mb-2">Diagram preview requires a Mermaid renderer. Source:</p>
            <pre
              className="whitespace-pre-wrap font-mono text-xs p-2 rounded"
              style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}
            >
              {artifact.content}
            </pre>
          </div>
        ) : (
          <pre
            className="whitespace-pre-wrap overflow-auto font-mono text-xs max-h-80 p-2 rounded"
            style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)" }}
          >
            {artifact.content}
          </pre>
        )}
      </div>
    </div>
  );
}

export default function ArtifactRenderer({ content }: { content: string }) {
  const extracted = useMemo(() => extractArtifacts(content), [content]);

  if (extracted.length === 0) {
    return (
      <div className="text-sm leading-relaxed prose prose-invert max-w-none">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>
      </div>
    );
  }

  return (
    <>
      {extracted.map((item, i) => (
        <div key={i}>
          {item.text.trim() && (
            <div className="text-sm leading-relaxed prose prose-invert max-w-none mb-2">
              <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{item.text}</ReactMarkdown>
            </div>
          )}
          <ArtifactCard artifact={item.payload} />
        </div>
      ))}
    </>
  );
}
