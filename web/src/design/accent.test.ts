import { describe, expect, it } from "vitest";

import {
  ACCENT_PRESETS,
  type AccentTheme,
  contrastRatio,
  generateAccentPalette,
  relativeLuminance,
  THEME_BACKGROUND,
  THEME_CARD,
} from "./accent";

const WHITE = "#ffffff";
const THEMES: AccentTheme[] = ["dark", "light", "midnight"];
// Measured against the values the themes publish, never a copy of them: a literal here is a second
// source of truth that goes stale the moment tokens.json moves.
const BACKGROUNDS = THEME_BACKGROUND;
const CARDS = THEME_CARD;

/** The surfaces a button label can sit on, in every state the picker can produce. */
const LABEL_SURFACES = ["default", "hover", "active"] as const;

function hueOf(hex: string): number {
  const c = hex.replace("#", "");
  const r = Number.parseInt(c.slice(0, 2), 16) / 255;
  const g = Number.parseInt(c.slice(2, 4), 16) / 255;
  const b = Number.parseInt(c.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return -1;
  let h = 0;
  if (max === r) h = ((g - b) / delta) % 6;
  else if (max === g) h = (b - r) / delta + 2;
  else h = (r - g) / delta + 4;
  return (h * 60 + 360) % 360;
}

describe("accent palette generation", () => {
  it.each(ACCENT_PRESETS.flatMap((preset) => THEMES.map((theme) => [preset, theme] as const)))(
    "keeps white button labels readable for %s on %s",
    (preset, theme) => {
      const palette = generateAccentPalette(preset.hex, theme);
      for (const surface of LABEL_SURFACES) {
        const ratio = contrastRatio(WHITE, palette[surface]);
        expect(ratio, `white on ${surface} ${palette[surface]} (${preset.name}/${theme})`).toBeGreaterThanOrEqual(4.5);
      }
    }
  );

  it.each(ACCENT_PRESETS.flatMap((preset) => THEMES.map((theme) => [preset, theme] as const)))(
    "keeps links readable against the page for %s on %s",
    (preset, theme) => {
      const palette = generateAccentPalette(preset.hex, theme);
      const background = BACKGROUNDS[theme];
      expect(contrastRatio(palette.textLink, background), `link ${preset.name}/${theme}`).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette.textLinkHover, background), `link hover ${preset.name}/${theme}`).toBeGreaterThanOrEqual(
        4.5
      );
      // a focus ring is a UI part, so 3:1 is the published minimum — against the page it sits on, and
      // against the card every interactive control is actually drawn on
      expect(contrastRatio(palette.borderFocus, background), `focus ${preset.name}/${theme}`).toBeGreaterThanOrEqual(3);
      expect(
        contrastRatio(palette.borderFocus, CARDS[theme]),
        `focus on card ${preset.name}/${theme}`
      ).toBeGreaterThanOrEqual(3);
    }
  );

  it.each(ACCENT_PRESETS)("preserves the hue of %s while clamping its lightness", (preset) => {
    const generated = generateAccentPalette(preset.hex, "dark");
    const drift = Math.abs(hueOf(generated.default) - hueOf(preset.hex));
    expect(drift, `${preset.name} drifted to ${generated.default}`).toBeLessThan(1);
  });

  it("does not darken the brand default, which already passes", () => {
    expect(generateAccentPalette("#7c3aed", "dark").default).toBe("#7c3aed");
  });

  it("brightens a link on a dark page instead of darkening it", () => {
    const palette = generateAccentPalette("#7c3aed", "midnight");
    expect(relativeLuminance(palette.textLink)).toBeGreaterThan(relativeLuminance(BACKGROUNDS.midnight));
  });
});
