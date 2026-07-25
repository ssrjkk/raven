import { Sparkles } from "lucide-react";
import { memo } from "react";

interface Props {
  inputTokens?: number;
  outputTokens?: number;
  cost?: number;
  durationMs?: number;
  model?: string;
  compact?: boolean;
}

const TokenUsageBar = memo(function TokenUsageBar({ inputTokens, outputTokens, cost, durationMs, model, compact }: Props) {
  if (inputTokens == null && outputTokens == null && cost == null) return null;

  const total = (inputTokens ?? 0) + (outputTokens ?? 0);
  const dur = durationMs ? formatDuration(durationMs) : null;

  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded bg-tertiary text-tertiary">
        <Sparkles className="w-2.5 h-2.5" style={{ color: "var(--dt-colors-accent-default)" }} />
        <span>{total.toLocaleString()} tok</span>
        {cost != null && <span>${cost.toFixed(5)}</span>}
        {dur && <span>{dur}</span>}
      </div>
    );
  }

  return (
    <div className="rounded-lg p-3 text-xs font-mono space-y-1.5"
      style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", border: "1px solid var(--dt-colors-border-default)" }}>
      <div className="flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5" style={{ color: "var(--dt-colors-accent-default)" }} />
        <span className="text-secondary">Token Usage</span>
        {model && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: "var(--dt-colors-bg-secondary)", color: "var(--dt-colors-text-tertiary)" }}>{model}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-tertiary">
        <span>Input: <strong className="text-primary">{(inputTokens ?? 0).toLocaleString()}</strong> tok</span>
        <span>Output: <strong className="text-primary">{(outputTokens ?? 0).toLocaleString()}</strong> tok</span>
        <span>Total: <strong className="text-primary">{total.toLocaleString()}</strong> tok</span>
        <span>Cost: <strong style={{ color: cost != null && cost > 0.01 ? "var(--dt-colors-danger-default)" : "var(--dt-colors-text-primary)" }}>${(cost ?? 0).toFixed(6)}</strong></span>
        {dur && <span className="col-span-2">Duration: <strong className="text-primary">{dur}</strong></span>}
      </div>
    </div>
  );
});

export default TokenUsageBar;

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}
