import { FileDiff } from "lucide-react";
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

/** The three states a diff row has, each with the tint, the ink and the sign it reports with. */
const DIFF_KIND: Record<DiffLine["type"], { tint: string; ink: string; sign: string }> = {
  add: { tint: "diff-add", ink: "text-success", sign: "+" },
  del: { tint: "diff-del", ink: "text-danger", sign: "-" },
  ctx: { tint: "", ink: "text-primary", sign: " " },
};

const DiffViewer = memo(function DiffViewer({ diff, files, singlePane, maxHeight = "70vh" }: Props) {
  const parsed = useMemo(() => parseDiff(diff), [diff]);

  if (!diff) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-sm text-tertiary">
        <FileDiff size={22} className="mb-2" />
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
              {f.added > 0 && <span className="ml-1 text-success">+{f.added}</span>}
              {f.deleted > 0 && <span className="ml-1 text-danger">-{f.deleted}</span>}
            </span>
          ))}
        </div>
      )}

      <div className="overflow-auto" style={{ maxHeight }}>
        {parsed.length === 0 ? (
          <pre className="p-4 text-xs font-mono whitespace-pre-wrap text-secondary bg-primary">
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
          const kind = DIFF_KIND[line.type];
          return (
            <tr key={i}>
              <td className="diff-gutter select-none text-right px-2 py-0 w-12 align-top">
                {line.type === "ctx" ? line.oldLine : ""}
              </td>
              <td className="diff-gutter select-none text-right px-2 py-0 w-12 align-top">
                {line.type === "ctx" ? line.newLine : ""}
              </td>
              <td className={`px-2 py-0 align-top whitespace-pre ${kind.tint}`}>
                <span className={kind.ink}>
                  {kind.sign}{line.content}
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
          <th className="diff-gutter text-right px-2 py-1 w-12 font-normal">Old</th>
          <th className="diff-gutter text-right px-2 py-1 w-12 font-normal">New</th>
          <th className="text-left px-2 py-1 font-normal text-tertiary">&nbsp;</th>
          <th className="diff-gutter text-right px-2 py-1 w-12 font-normal">Old</th>
          <th className="diff-gutter text-right px-2 py-1 w-12 font-normal">New</th>
          <th className="text-left px-2 py-1 font-normal text-tertiary">&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {chunkLines(lines).map((chunk, ci) => (
          <tr key={ci}>
            <DiffCells line={chunk.left} />
            <DiffCells line={chunk.right} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One half of a side-by-side row: the two gutter numbers and the line itself, or the gap where they would be. */
function DiffCells({ line }: { line: DiffLine | null }) {
  if (!line) return <td colSpan={3} />;
  const kind = DIFF_KIND[line.type];
  return (
    <>
      <td className="diff-gutter text-right px-2 py-0 w-12 select-none align-top">{line.oldLine || ""}</td>
      <td className="diff-gutter text-right px-2 py-0 w-12 select-none align-top">{line.newLine || ""}</td>
      <td className={`px-2 py-0 align-top whitespace-pre ${kind.tint}`}>
        <span className={kind.ink}>
          {kind.sign}
          {line.content}
        </span>
      </td>
    </>
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
