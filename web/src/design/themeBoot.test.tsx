import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SHELL from "../../index.html?raw";
import { ThemeProvider, useTheme } from "./ThemeContext";

/**
 * The inline script in `web/index.html` paints the first frame; `ThemeProvider` paints every frame after it.
 *
 * They answer the same question in two languages, and the shell cannot import the module -- it runs before the
 * bundle exists -- so the only honest check is to run the shipped script and the shipped provider against the
 * same storage and the same `prefers-color-scheme`, and require the same answer. Measured this way, drift in
 * either one fails here: a theme the script invents, a rule the module adds, or a `theme-color` hex that no
 * longer matches the palette the console paints with.
 */

/** The script the document runs before the bundle exists: the one inline block that names the theme. */
function bootScript(): string {
  const blocks = [...SHELL.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
  const script = blocks.find((block) => /data-theme/.test(block));
  expect(script, "index.html holds no inline theme script, so the first paint is unmeasured").toBeTruthy();
  return script as string;
}

/** The `theme-color` meta exactly as the document declares it, so the script has something to rewrite. */
function themeColorTag(): string {
  const tag = /<meta name="theme-color"[^>]*>/.exec(SHELL);
  expect(tag, "index.html declares no theme-color meta, so the browser's chrome colour is unmeasured").toBeTruthy();
  return (tag as RegExpExecArray)[0];
}

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="theme">{theme}</span>;
}

const THEMES = [null, "light", "dark", "midnight", "auto", "not-a-theme"] as const;

describe("the theme the shell paints before the bundle runs", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.className = "";
    document.head.replaceChildren();
  });

  for (const prefersLight of [false, true]) {
    for (const stored of THEMES) {
      const label = `${stored ?? "nothing stored"} under prefers-color-scheme: ${prefersLight ? "light" : "dark"}`;

      it(`answers it the way the console answers it: ${label}`, () => {
        vi.stubGlobal("matchMedia", (query: string) => ({
          matches: /light/.test(query) === prefersLight,
          media: query,
          onchange: null,
          addListener: () => {},
          removeListener: () => {},
          addEventListener: () => {},
          removeEventListener: () => {},
          dispatchEvent: () => false,
        }));
        if (stored !== null) localStorage.setItem("raven-theme", stored);
        document.head.innerHTML = themeColorTag();

        new Function(bootScript())();
        const painted = {
          theme: document.documentElement.getAttribute("data-theme"),
          color: document.querySelector("meta[name=theme-color]")?.getAttribute("content") ?? null,
        };

        render(
          <ThemeProvider>
            <Probe />
          </ThemeProvider>,
        );
        const mounted = {
          theme: screen.getByTestId("theme").textContent,
          color: document.querySelector("meta[name=theme-color]")?.getAttribute("content") ?? null,
        };

        // A shell that paints one theme and mounts another is a flash of the wrong palette on every cold
        // start, and the operator reads the colour of the tab before either of them settles.
        expect(
          painted.theme,
          `${label}: the shell painted ${painted.theme} and the console mounted ${mounted.theme}`,
        ).toBe(mounted.theme);
        expect(painted.color, `${label}: the shell announced ${painted.color} and the console ${mounted.color}`).toBe(
          mounted.color,
        );
      });
    }
  }

  it("rewrites a theme-color the document has already declared", () => {
    // The script sets the colour of the browser's chrome by finding the meta and writing to it, and an element
    // the parser has not reached is not in the document yet. Declared below the script, the meta kept its
    // fallback value on every cold start -- the tab stayed dark navy for a light and a midnight operator alike
    // -- and only a reader that executes the document in order could see it.
    const metaAt = SHELL.indexOf(themeColorTag());
    const scriptAt = SHELL.indexOf(bootScript());
    expect(metaAt, "no theme-color meta to rewrite").toBeGreaterThan(-1);
    expect(scriptAt, "no inline theme script to run").toBeGreaterThan(-1);
    expect(metaAt, "the theme-color meta is declared after the script that rewrites it").toBeLessThan(scriptAt);
  });

  it("leaves the html element's class alone, which is not the console's to keep in step", () => {
    // `applyTokens` moves the palette by `data-theme` only, and no stylesheet in the app selects on
    // `html.dark`: a class the script set and the provider never cleared would keep naming the old theme
    // after the operator toggled, for whatever selector reads it next.
    document.head.innerHTML = themeColorTag();
    document.documentElement.className = "booted";
    new Function(bootScript())();
    expect(document.documentElement.className).toBe("booted");
  });
});
