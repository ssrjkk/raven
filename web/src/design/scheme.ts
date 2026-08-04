export type ColorPalette = Record<string, Record<string, string>>;

export function applyThemeScheme(palette: ColorPalette) {
  const root = document.documentElement;
  for (const [group, colors] of Object.entries(palette)) {
    for (const [key, value] of Object.entries(colors)) {
      root.style.setProperty(`--dt-colors-${group}-${key}`, value);
    }
  }
}

export function clearThemeScheme(groups: string[]) {
  const root = document.documentElement;
  for (const group of groups) {
    for (const el of Array.from(root.style)) {
      if (el.startsWith(`--dt-colors-${group}-`)) {
        root.style.removeProperty(el);
      }
    }
  }
}
