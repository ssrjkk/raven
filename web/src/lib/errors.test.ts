import { describe, expect, it } from "vitest";

import { errorMessage } from "./errors";

describe("errorMessage", () => {
  it("shows what the api threw", () => {
    expect(errorMessage(new Error("API /api/rag/search: 500"))).toBe("API /api/rag/search: 500");
  });

  it("falls back when the error carries no text", () => {
    expect(errorMessage(new Error())).toBe("Request failed");
    expect(errorMessage(new Error("   "), "Index failed")).toBe("Index failed");
  });

  it("shows a rejection that is a bare string", () => {
    expect(errorMessage("upload rejected")).toBe("upload rejected");
    expect(errorMessage("  spaced  ")).toBe("spaced");
    expect(errorMessage("")).toBe("Request failed");
  });

  it("reads the detail field FastAPI answers with", () => {
    expect(errorMessage({ detail: "Rate limit exceeded" })).toBe("Rate limit exceeded");
    expect(errorMessage({ error: "no such monitor" })).toBe("no such monitor");
    expect(errorMessage({ message: "gone" })).toBe("gone");
  });

  it("prefers message over detail when both are present", () => {
    expect(errorMessage({ message: "first", detail: "second" })).toBe("first");
  });

  it("never returns undefined, which is what made a failure invisible", () => {
    for (const value of [undefined, null, 42, true, {}, [], { detail: 7 }, () => 0]) {
      expect(errorMessage(value, "Search failed")).toBe("Search failed");
    }
  });

  it("does not crash on the shapes a page can actually receive", () => {
    expect(() => errorMessage(undefined)).not.toThrow();
    expect(typeof errorMessage(new Error("x"))).toBe("string");
  });
});
