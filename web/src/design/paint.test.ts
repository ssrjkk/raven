import { beforeEach, describe, expect, it } from "vitest";

import { contrastRatio } from "./accent";
import { labelOn, readToken } from "./paint";

/**
 * `labelOn` is what decides the text on a categorical fill (plugin tags) and on anything a canvas
 * paints, so it is the one place allowed to choose a colour at runtime. The two candidates are the
 * theme's own inverses, which is why the choice flips between themes rather than the palette.
 */
describe("labelOn", () => {
  beforeEach(() => {
    document.documentElement.style.setProperty("--dt-colors-bg-inverse", "#ffffff");
    document.documentElement.style.setProperty("--dt-colors-text-inverse", "#09090b");
  });

  it("keeps white on a dark fill", () => {
    expect(labelOn("#7c3aed")).toBe("#ffffff");
  });

  it("switches to ink on a bright fill where white measures 1.92:1", () => {
    expect(labelOn("#eab308")).toBe("#09090b");
    expect(labelOn("#22c55e")).toBe("#09090b");
    expect(labelOn("#d946ef")).toBe("#09090b");
  });

  it("always clears AA against the fill it was asked about", () => {
    for (const fill of ["#7c3aed", "#eab308", "#22c55e", "#d946ef", "#059db6", "#0f1117", "#f6f7fb"]) {
      expect(contrastRatio(labelOn(fill), fill)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("reads the token the theme publishes, not a copy of it", () => {
    document.documentElement.style.setProperty("--dt-colors-status-error", "#dc2626");
    expect(readToken("--dt-colors-status-error")).toBe("#dc2626");
    expect(readToken("--dt-colors-never-published")).toBe("");
  });
});
