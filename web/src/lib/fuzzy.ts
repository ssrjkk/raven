export interface FuzzyResult {
  score: number;
  indices: number[];
}

const WORD_BOUNDARIES = new Set([" ", "-", "_", "/", ".", ":"]);

function isWordBoundary(target: string, index: number): boolean {
  if (index === 0) return true;
  return WORD_BOUNDARIES.has(target[index - 1]);
}

export function fuzzyMatch(query: string, target: string): FuzzyResult | null {
  const q = query.toLowerCase().trim();
  if (!q) return { score: 1, indices: [] };

  const substringIndex = target.toLowerCase().indexOf(q);
  if (substringIndex !== -1) {
    const indices: number[] = [];
    for (let i = 0; i < q.length; i++) indices.push(substringIndex + i);
    return { score: 100 + q.length, indices };
  }

  const indices: number[] = [];
  let qi = 0;
  let score = 0;
  let last = -2;
  let streak = 0;
  for (let ti = 0; ti < target.length && qi < q.length; ti++) {
    if (target[ti].toLowerCase() !== q[qi]) continue;
    qi++;
    indices.push(ti);
    streak = ti === last + 1 ? streak + 1 : 1;
    score += 1 + (streak - 1) * 2;
    if (isWordBoundary(target, ti)) score += 4;
    last = ti;
  }

  if (qi < q.length) return null;
  return { score: score / Math.max(1, target.length), indices };
}

export function sortByFuzzyScore<T>(
  items: readonly T[],
  query: string,
  getText: (item: T) => string
): { item: T; score: number; indices: number[] }[] {
  const scored: { item: T; score: number; indices: number[] }[] = [];
  for (const item of items) {
    const result = fuzzyMatch(query, getText(item));
    if (result === null) continue;
    scored.push({ item, score: result.score, indices: result.indices });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored;
}
