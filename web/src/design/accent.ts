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

export function generateAccentPalette(hex: string, theme: AccentTheme = "dark"): AccentPalette {
  const lightMode = theme === "light";
  return {
    default: hex,
    hover: lightMode ? darken(hex, 0.08) : lighten(hex, 0.12),
    active: lightMode ? darken(hex, 0.18) : darken(hex, 0.12),
    muted: toRgba(hex, 0.15),
    subtle: toRgba(hex, 0.08),
    borderFocus: hex,
    textLink: lightMode ? darken(hex, 0.08) : lighten(hex, 0.18),
    textLinkHover: lightMode ? darken(hex, 0.18) : lighten(hex, 0.32),
    glow: toRgba(hex, 0.4),
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
