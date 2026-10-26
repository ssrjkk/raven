function hexToRgb(hex: string): [number, number, number] {
  const c = hex.replace("#", "");
  return [
    Number.parseInt(c.slice(0, 2), 16),
    Number.parseInt(c.slice(2, 4), 16),
    Number.parseInt(c.slice(4, 6), 16),
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  const to = (n: number) => Math.round(Math.max(0, Math.min(255, n))).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function lighten(hex: string, amount: number): string {
  const [r, g, b] = hexToRgb(hex);
  return rgbToHex(lerp(r, 255, amount), lerp(g, 255, amount), lerp(b, 255, amount));
}

export function darken(hex: string, amount: number): string {
  const [r, g, b] = hexToRgb(hex);
  return rgbToHex(lerp(r, 0, amount), lerp(g, 0, amount), lerp(b, 0, amount));
}

export function toRgba(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function channelLuminance(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b);
}

export function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a);
  const second = relativeLuminance(b);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

export type AccentTheme = "dark" | "light" | "midnight";

export interface AccentPalette {
  default: string;
  hover: string;
  active: string;
  muted: string;
  subtle: string;
  borderFocus: string;
  textLink: string;
  textLinkHover: string;
  glow: string;
}

/** WCAG 2.1 minima: 4.5:1 for normal text, 3:1 for a UI part such as a focus ring. */
const NORMAL_TEXT = 4.5;
const UI_PART = 3.0;
const WHITE = "#ffffff";

/** The page background of each theme: the accent is measured against a surface, not in the abstract.
 * Single source for ThemeContext's meta theme-color as well, so the two cannot drift apart. */
export const THEME_BACKGROUND: Record<AccentTheme, string> = {
  dark: "#0f1117",
  light: "#f6f7fb",
  midnight: "#050507",
};

/**
 * Keeps hue and chroma and moves lightness until white button labels clear `target`. Without this,
 * picking a bright preset (Lime, Amber, Sky) made every button in the application unreadable, and
 * the hover state lightened further still.
 */
function readableOnWhite(hex: string, target: number): string {
  let current = hex;
  for (let step = 0; step <= 100 && contrastRatio(WHITE, current) < target; step += 1) {
    current = darken(hex, step / 100);
  }
  return current;
}

/** Moves the colour away from the surface it sits on, in the direction that surface needs. Exported
 * because chart series need the same measurement against the panel they are drawn on. */
export function readableAgainst(hex: string, background: string, target: number): string {
  if (contrastRatio(hex, background) >= target) return hex;
  const towardsWhite = relativeLuminance(background) < 0.5;
  let current = hex;
  for (let step = 1; step <= 100; step += 1) {
    current = towardsWhite ? lighten(hex, step / 100) : darken(hex, step / 100);
    if (contrastRatio(current, background) >= target) return current;
  }
  return current;
}

export function generateAccentPalette(hex: string, theme: AccentTheme = "dark"): AccentPalette {
  const background = THEME_BACKGROUND[theme];
  const surface = readableOnWhite(hex, NORMAL_TEXT);
  const link = readableAgainst(surface, background, NORMAL_TEXT);
  return {
    default: surface,
    hover: darken(surface, 0.08),
    active: darken(surface, 0.16),
    muted: toRgba(surface, 0.15),
    subtle: toRgba(surface, 0.08),
    borderFocus: readableAgainst(surface, background, UI_PART),
    textLink: link,
    textLinkHover: readableAgainst(lighten(link, 0.1), background, NORMAL_TEXT),
    glow: toRgba(surface, 0.4),
  };
}

export const ACCENT_PRESETS = [
  { name: "Purple", hex: "#7c3aed" },
  { name: "Violet", hex: "#8b5cf6" },
  { name: "Indigo", hex: "#6366f1" },
  { name: "Blue", hex: "#3b82f6" },
  { name: "Sky", hex: "#0ea5e9" },
  { name: "Cyan", hex: "#06b6d4" },
  { name: "Teal", hex: "#14b8a6" },
  { name: "Green", hex: "#22c55e" },
  { name: "Lime", hex: "#84cc16" },
  { name: "Amber", hex: "#f59e0b" },
  { name: "Orange", hex: "#f97316" },
  { name: "Red", hex: "#ef4444" },
  { name: "Rose", hex: "#f43f5e" },
  { name: "Pink", hex: "#ec4899" },
  { name: "Fuchsia", hex: "#d946ef" },
  { name: "Slate", hex: "#64748b" },
] as const;

export function applyAccentPalette(palette: AccentPalette) {
  const root = document.documentElement;
  root.style.setProperty("--dt-colors-accent-default", palette.default);
  root.style.setProperty("--dt-colors-accent-hover", palette.hover);
  root.style.setProperty("--dt-colors-accent-active", palette.active);
  root.style.setProperty("--dt-colors-accent-muted", palette.muted);
  root.style.setProperty("--dt-colors-accent-subtle", palette.subtle);
  root.style.setProperty("--dt-colors-border-focus", palette.borderFocus);
  root.style.setProperty("--dt-colors-text-link", palette.textLink);
  root.style.setProperty("--dt-colors-text-link-hover", palette.textLinkHover);
  root.style.setProperty("--dt-shadow-glow-accent", `0 0 12px ${palette.glow}`);
}
