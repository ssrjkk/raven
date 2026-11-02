import { fuzzyMatch, FuzzyResult } from "./fuzzy";

export interface SearchableCommand {
  id: string;
  label: string;
  keywords?: string[];
}

interface Scored<T> {
  cmd: T;
  indices: number[];
  priority: number;
}

/** Rank commands against a palette query.

    A label hit outranks an alias hit, and an alias hit carries no highlight: its indices point
    into the search-only alias, not into the English text the palette actually renders. */
export function rankCommands<T extends SearchableCommand>(query: string, commands: T[]): { cmd: T; indices: number[] }[] {
  const q = query.toLowerCase().trim();
  if (!q) return commands.map((cmd) => ({ cmd, indices: [] }));

  const scored: Scored<T>[] = [];
  for (const cmd of commands) {
    const labelHit: FuzzyResult | null = fuzzyMatch(q, cmd.label);
    let aliasHit: FuzzyResult | null = null;
    for (const word of cmd.keywords ?? []) {
      const hit = fuzzyMatch(q, word);
      if (hit && (!aliasHit || hit.score > aliasHit.score)) aliasHit = hit;
    }
    const match = labelHit ?? aliasHit;
    if (!match) continue;
    scored.push({
      cmd,
      indices: labelHit ? labelHit.indices : [],
      priority: labelHit ? labelHit.score + 100 : match.score,
    });
  }
  return scored.sort((a, b) => b.priority - a.priority).map(({ cmd, indices }) => ({ cmd, indices }));
}
