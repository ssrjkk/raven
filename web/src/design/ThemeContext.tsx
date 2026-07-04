import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import darkTokens from "./tokens.json";
import lightTokens from "./tokens.light.json";

type Theme = "dark" | "light";

type ThemeContextValue = {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  toggleTheme: () => {},
  setTheme: () => {},
});

function getInitialTheme(): Theme {
  const stored = localStorage.getItem("raven-theme");
  if (stored === "light" || stored === "dark") return stored;
  if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
  return "dark";
}

function applyTokens(theme: Theme) {
  const tokens = theme === "dark" ? darkTokens : lightTokens;
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

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    applyTokens(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("raven-theme", next);
      return next;
    });
  }, []);

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem("raven-theme", t);
    setThemeState(t);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
