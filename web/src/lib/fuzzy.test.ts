import { describe, expect, it } from "vitest";

import { fuzzyMatch, sortByFuzzyScore } from "./fuzzy";

describe("fuzzyMatch", () => {
  it("returns empty match for empty query", () => {
    const result = fuzzyMatch("", "anything");
    expect(result).toEqual({ score: 1, indices: [] });
  });

  it("exact substring gets top score", () => {
    const exact = fuzzyMatch("settings", "Settings");
    const fuzzy = fuzzyMatch("stgs", "Settings");
    expect(exact).not.toBeNull();
    expect(fuzzy).not.toBeNull();
    expect(exact!.score).toBeGreaterThan(fuzzy!.score);
  });

  it("matches subsequence with word boundary bonus", () => {
    const result = fuzzyMatch("cd", "Coder Debugger");
    expect(result).not.toBeNull();
    expect(result!.indices).toEqual([0, 2]);
  });

  it("returns null when not a subsequence", () => {
    expect(fuzzyMatch("zzz", "settings")).toBeNull();
  });

  it("is case insensitive", () => {
    const result = fuzzyMatch("SET", "settings");
    expect(result).not.toBeNull();
    expect(result!.score).toBeGreaterThan(0);
  });

  it("prefers consecutive matches over scattered ones", () => {
    const scattered = fuzzyMatch("cdb", "Coder Debugger");
    const consecutive = fuzzyMatch("cdd", "Coder Debugger");
    expect(scattered).not.toBeNull();
    expect(consecutive).not.toBeNull();
    expect(consecutive!.score).toBeGreaterThan(scattered!.score);
  });

  it("matches cyrillic", () => {
    const result = fuzzyMatch("пер", "Переключить тему");
    expect(result).not.toBeNull();
  });
});

describe("sortByFuzzyScore", () => {
  const items = [
    { name: "Settings" },
    { name: "Code Sessions" },
    { name: "Git" },
    { name: "Готово" },
  ];

  it("filters out non-matches", () => {
    const result = sortByFuzzyScore(items, "qqqq", (i) => i.name);
    expect(result).toHaveLength(0);
  });

  it("sorts by descending score", () => {
    const result = sortByFuzzyScore(items, "set", (i) => i.name);
    expect(result.length).toBeGreaterThan(0);
    const scores = result.map((r) => r.score);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
  });

  it("keeps original items", () => {
    const result = sortByFuzzyScore(items, "git", (i) => i.name);
    expect(result[0].item.name).toBe("Git");
  });
});
