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
      <div className="inline-flex items-center gap-1.5 text-micro font-mono px-1.5 py-0.5 rounded bg-tertiary text-tertiary">
        <Sparkles className="w-2.5 h-2.5 text-accent" />
        <span>{total.toLocaleString()} tok</span>
        {cost != null && <span>${cost.toFixed(5)}</span>}
        {dur && <span>{dur}</span>}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-default bg-tertiary p-3 text-xs font-mono space-y-1.5">
      <div className="flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-accent" />
        <span className="text-secondary">Token Usage</span>
        {model && <span className="text-micro px-1.5 py-0.5 rounded bg-secondary text-tertiary">{model}</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-caption text-tertiary">
        <span>Input: <strong className="text-primary">{(inputTokens ?? 0).toLocaleString()}</strong> tok</span>
        <span>Output: <strong className="text-primary">{(outputTokens ?? 0).toLocaleString()}</strong> tok</span>
        <span>Total: <strong className="text-primary">{total.toLocaleString()}</strong> tok</span>
        <span>Cost: <strong className={cost != null && cost > 0.01 ? "text-danger" : "text-primary"}>${(cost ?? 0).toFixed(6)}</strong></span>
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
