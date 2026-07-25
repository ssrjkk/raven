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

export function generateAccentPalette(hex: string): AccentPalette {
  return {
    default: hex,
    hover: lighten(hex, 0.12),
    active: darken(hex, 0.12),
    muted: toRgba(hex, 0.15),
    subtle: toRgba(hex, 0.08),
    borderFocus: hex,
    textLink: lighten(hex, 0.18),
    textLinkHover: lighten(hex, 0.3),
    glow: toRgba(hex, 0.4),
  };
}

export const ACCENT_PRESETS = [
  { name: "Purple", hex: "#7c3aed" },
  { name: "Blue", hex: "#3b82f6" },
  { name: "Green", hex: "#22c55e" },
  { name: "Teal", hex: "#14b8a6" },
  { name: "Orange", hex: "#f97316" },
  { name: "Red", hex: "#ef4444" },
  { name: "Pink", hex: "#ec4899" },
  { name: "Amber", hex: "#f59e0b" },
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
