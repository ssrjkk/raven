import { contrastRatio } from "./accent";

/** Resolve a design token to the colour the current theme publishes for it. */
export function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * The label colour that a saturated fill can carry, picked from the two the theme already publishes:
 * `bg.inverse` and `text.inverse` are each other's opposite in every theme, so one of them always
 * reads. Canvas and badge colours are chosen at runtime, so the answer cannot be a token of its own.
 */
export function labelOn(fill: string): string {
  const light = readToken("--dt-colors-bg-inverse");
  const dark = readToken("--dt-colors-text-inverse");
  return contrastRatio(light, fill) >= contrastRatio(dark, fill) ? light : dark;
}
