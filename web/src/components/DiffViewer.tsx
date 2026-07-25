import { memo, useMemo } from "react";

interface DiffLine {
  type: "add" | "del" | "ctx";
  oldLine: number;
  newLine: number;
  content: string;
}

export interface DiffFile {
  path: string;
  added: number;
  deleted: number;
}

interface Props {
  diff: string;
  files?: DiffFile[];
  singlePane?: boolean;
  maxHeight?: string;
}

const DiffViewer = memo(function DiffViewer({ diff, files, singlePane, maxHeight = "70vh" }: Props) {
  const parsed = useMemo(() => parseDiff(diff), [diff]);

  if (!diff) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-sm text-tertiary">
        <span className="text-2xl mb-2">РІвЂЎвЂћ</span>
        <span>No diff to display</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl overflow-hidden border border-default">
      {files && files.length > 0 && (
        <div className="px-3 py-2 border-b flex flex-wrap gap-3 text-xs border-default bg-secondary">
          <span className="text-secondary">
            {files.length} file{files.length !== 1 ? "s" : ""} changed
          </span>
          {files.map((f) => (
            <span key={f.path} className="font-mono text-tertiary">
              {f.path}
              {f.added > 0 && <span className="text-green-500 ml-1">+{f.added}</span>}
              {f.deleted > 0 && <span className="text-red-500 ml-1">-{f.deleted}</span>}
            </span>
          ))}
        </div>
      )}

      <div className="overflow-auto" style={{ maxHeight }}>
        {parsed.length === 0 ? (
          <pre className="p-4 text-xs font-mono whitespace-pre-wrap" style={{ color: "var(--dt-colors-text-secondary)", backgroundColor: "var(--dt-colors-bg-primary)" }}>
            {diff.slice(0, 10000)}
          </pre>
        ) : singlePane ? (
          <SinglePaneView lines={parsed} />
        ) : (
          <SideBySideView lines={parsed} />
        )}
      </div>
    </div>
  );
});

export default DiffViewer;

function SinglePaneView({ lines }: { lines: DiffLine[] }) {
  return (
    <table className="w-full text-xs font-mono border-collapse">
      <tbody>
        {lines.map((line, i) => {
          let bg = "transparent";
          let prefix = " ";
          if (line.type === "add") { bg = "rgba(34,197,94,0.08)"; prefix = "+"; }
          else if (line.type === "del") { bg = "rgba(239,68,68,0.08)"; prefix = "-"; }
          return (
            <tr key={i}>
              <td className="select-none text-right px-2 py-0 w-12 align-top" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                {line.type === "ctx" ? line.oldLine : ""}
              </td>
              <td className="select-none text-right px-2 py-0 w-12 align-top" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                {line.type === "ctx" ? line.newLine : ""}
              </td>
              <td className="px-2 py-0 align-top whitespace-pre" style={{ backgroundColor: bg }}>
                <span style={{ color: line.type === "add" ? "#22c55e" : line.type === "del" ? "#ef4444" : "var(--dt-colors-text-primary)" }}>
                  {prefix}{escapeHtml(line.content)}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SideBySideView({ lines }: { lines: DiffLine[] }) {
  return (
    <table className="w-full text-xs font-mono border-collapse">
      <thead>
        <tr className="bg-secondary">
          <th className="text-right px-2 py-1 w-12 font-normal" style={{ color: "var(--dt-colors-text-tertiary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>Old</th>
          <th className="text-right px-2 py-1 w-12 font-normal" style={{ color: "var(--dt-colors-text-tertiary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>New</th>
          <th className="text-left px-2 py-1 font-normal text-tertiary">&nbsp;</th>
          <th className="text-right px-2 py-1 w-12 font-normal" style={{ color: "var(--dt-colors-text-tertiary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>Old</th>
          <th className="text-right px-2 py-1 w-12 font-normal" style={{ color: "var(--dt-colors-text-tertiary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>New</th>
          <th className="text-left px-2 py-1 font-normal text-tertiary">&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {chunkLines(lines).map((chunk, ci) => (
          <tr key={ci}>
            {chunk.left ? (
              <>
                <td className="text-right px-2 py-0 align-top w-12 select-none" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                  {chunk.left.oldLine || ""}
                </td>
                <td className="text-right px-2 py-0 align-top w-12 select-none" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                  {chunk.left.newLine || ""}
                </td>
                <td className="px-2 py-0 align-top whitespace-pre" style={{ backgroundColor: chunk.left.type === "add" ? "rgba(34,197,94,0.08)" : chunk.left.type === "del" ? "rgba(239,68,68,0.08)" : "transparent" }}>
                  <span style={{ color: chunk.left.type === "add" ? "#22c55e" : chunk.left.type === "del" ? "#ef4444" : "var(--dt-colors-text-primary)" }}>
                    {chunk.left.type === "add" ? "+" : chunk.left.type === "del" ? "-" : " "}{escapeHtml(chunk.left.content)}
                  </span>
                </td>
              </>
            ) : (
              <td colSpan={3} />
            )}
            {chunk.right ? (
              <>
                <td className="text-right px-2 py-0 align-top w-12 select-none" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                  {chunk.right.oldLine || ""}
                </td>
                <td className="text-right px-2 py-0 align-top w-12 select-none" style={{ color: "var(--dt-colors-text-tertiary)", backgroundColor: "var(--dt-colors-bg-secondary)", borderRight: "1px solid var(--dt-colors-border-default)" }}>
                  {chunk.right.newLine || ""}
                </td>
                <td className="px-2 py-0 align-top whitespace-pre" style={{ backgroundColor: chunk.right.type === "add" ? "rgba(34,197,94,0.08)" : chunk.right.type === "del" ? "rgba(239,68,68,0.08)" : "transparent" }}>
                  <span style={{ color: chunk.right.type === "add" ? "#22c55e" : chunk.right.type === "del" ? "#ef4444" : "var(--dt-colors-text-primary)" }}>
                    {chunk.right.type === "add" ? "+" : chunk.right.type === "del" ? "-" : " "}{escapeHtml(chunk.right.content)}
                  </span>
                </td>
              </>
            ) : (
              <td colSpan={3} />
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  for (const raw of diff.split("\n")) {
    const line = raw;
    if (line.startsWith("@@")) {
      const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        oldLine = Number(m[1]) - 1;
        newLine = Number(m[2]) - 1;
      }
      lines.push({ type: "ctx", oldLine: 0, newLine: 0, content: line });
      continue;
    }
    if (line.startsWith("diff --git") || line.startsWith("---") || line.startsWith("+++") || line.startsWith("index ")) {
      continue;
    }
    if (line.startsWith("+")) {
      newLine++;
      lines.push({ type: "add", oldLine: 0, newLine, content: line.slice(1) });
    } else if (line.startsWith("-")) {
      oldLine++;
      lines.push({ type: "del", oldLine, newLine: 0, content: line.slice(1) });
    } else {
      oldLine++;
      newLine++;
      lines.push({ type: "ctx", oldLine, newLine, content: line });
    }
  }
  return lines;
}

interface Chunk {
  left: DiffLine | null;
  right: DiffLine | null;
}

function chunkLines(lines: DiffLine[]): Chunk[] {
  const result: Chunk[] = [];
  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  for (const line of lines) {
    if (line.type === "del") left.push(line);
    else if (line.type === "add") right.push(line);
    else {
      flushLR();
      result.push({ left: line, right: line });
    }
  }
  flushLR();
  function flushLR() {
    const max = Math.max(left.length, right.length);
    for (let i = 0; i < max; i++) {
      result.push({ left: left[i] || null, right: right[i] || null });
    }
    left.length = 0;
    right.length = 0;
  }
  return result;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
