import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { applyAccentPalette, generateAccentPalette } from "./accent";
import darkTokens from "./tokens.json";
import lightTokens from "./tokens.light.json";
import midnightTokens from "./tokens.midnight.json";

export type Theme = "dark" | "light" | "midnight";

type ThemeContextValue = {
  theme: Theme;
  accentColor: string;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
  setAccentColor: (hex: string) => void;
  resetScheme: () => void;
};

const DEFAULT_ACCENT = "#7c3aed";

const THEME_ORDER: Theme[] = ["dark", "light", "midnight"];

const THEME_META: Record<Theme, string> = {
  dark: "#0f1117",
  light: "#f6f7fb",
  midnight: "#050507",
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  accentColor: DEFAULT_ACCENT,
  toggleTheme: () => {},
  setTheme: () => {},
  setAccentColor: () => {},
  resetScheme: () => {},
});

function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch (e) { console.error("ThemeContext:", e);
    return null;
  }
}

function safeSetItem(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch (e) { console.error("ThemeContext:", e);
    /* quota exceeded or private mode */
  }
}

function getInitialTheme(): Theme {
  const stored = safeGetItem("raven-theme");
  if (stored === "light" || stored === "dark" || stored === "midnight") return stored;
  try {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
  } catch (e) { console.error("ThemeContext:", e);
    /* matchMedia not supported */
  }
  return "dark";
}

function getInitialAccent(): string {
  const stored = safeGetItem("raven-accent");
  if (stored && /^#[0-9a-f]{6}$/i.test(stored)) return stored;
  return DEFAULT_ACCENT;
}

function applyTokens(theme: Theme) {
  const tokens = theme === "dark" ? darkTokens : theme === "light" ? lightTokens : midnightTokens;
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
  const flatten = (obj: Record<string, unknown>, prefix = "--dt") => {
    for (const [key, val] of Object.entries(obj)) {
      const name = `${prefix}-${key}`;
      if (val !== null && typeof val === "object") {
        flatten(val as Record<string, unknown>, name);
      } else {
        root.style.setProperty(name, String(val));
      }
    }
  };
  flatten(tokens as unknown as Record<string, unknown>);
}

function animateThemeSwitch() {
  const root = document.documentElement;
  root.classList.add("theme-anim");
  window.setTimeout(() => root.classList.remove("theme-anim"), 320);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);
  const [accentColor, setAccentColorState] = useState<string>(getInitialAccent);
  const firstRender = useRef(true);

  useEffect(() => {
    applyTokens(theme);
    const meta = document.querySelector("meta[name=theme-color]");
    if (meta) {
      meta.setAttribute("content", THEME_META[theme]);
    }
    if (firstRender.current) {
      firstRender.current = false;
    } else {
      animateThemeSwitch();
    }
  }, [theme]);

  useEffect(() => {
    const palette = generateAccentPalette(accentColor, theme);
    applyAccentPalette(palette);
  }, [accentColor, theme]);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = THEME_ORDER[(THEME_ORDER.indexOf(prev) + 1) % THEME_ORDER.length];
      safeSetItem("raven-theme", next);
      return next;
    });
  }, []);

  const setTheme = useCallback((t: Theme) => {
    safeSetItem("raven-theme", t);
    setThemeState(t);
  }, []);

  const setAccentColor = useCallback((hex: string) => {
    safeSetItem("raven-accent", hex);
    setAccentColorState(hex);
  }, []);

  const resetScheme = useCallback(() => {
    applyTokens(theme);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, accentColor, toggleTheme, setTheme, setAccentColor, resetScheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
