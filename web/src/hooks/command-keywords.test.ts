import { describe, expect, it } from "vitest";

import { COMMAND_KEYWORDS } from "./command-keywords";
import { rankCommands } from "../lib/command-search";

const commands = [
  { id: "toggle-theme", label: "Toggle theme", keywords: COMMAND_KEYWORDS["toggle-theme"] },
  { id: "generate-tests", label: "Generate tests", keywords: COMMAND_KEYWORDS["generate-tests"] },
  { id: "new-project", label: "Create a new project", keywords: COMMAND_KEYWORDS["new-project"] },
];

const ids = (query: string) => rankCommands(query, commands).map((entry) => entry.cmd.id);

describe("command search keeps working in the language the operator types in", () => {
  it("finds an English label from a Russian alias", () => {
    expect(ids("переключи тему")).toContain("toggle-theme");
    expect(ids("тесты")).toContain("generate-tests");
    expect(ids("проект")).toContain("new-project");
  });

  it("still finds the label itself, and ranks it above an alias hit", () => {
    expect(ids("theme")).toEqual(["toggle-theme"]);
    const both = rankCommands("тема", commands);
    expect(both[0].cmd.id).toBe("toggle-theme");
  });

  it("never highlights the label from an alias match", () => {
    const hit = rankCommands("тёмная", commands).find((entry) => entry.cmd.id === "toggle-theme");
    expect(hit?.indices).toEqual([]);
  });

  it("drops a command nothing matches and keeps the empty query whole", () => {
    expect(ids("zzzzq")).toEqual([]);
    expect(rankCommands("", commands)).toHaveLength(commands.length);
  });
});
