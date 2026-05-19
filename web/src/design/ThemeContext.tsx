import { createContext, useContext, useEffect, type ReactNode } from "react";
import tokens from "./tokens.json";

type Tokens = typeof tokens;

const ThemeContext = createContext<Tokens>(tokens);

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const root = document.documentElement;
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
  }, []);

  return <ThemeContext.Provider value={tokens}>{children}</ThemeContext.Provider>;
}

export function useTokens() {
  return useContext(ThemeContext);
}
