import { type Browser, expect, test } from "@playwright/test";

/**
 * The theme the shell paints before the bundle runs, measured against the theme the bundle settles on.
 *
 * `web/index.html` carries an inline script that sets `data-theme` and `theme-color` on the very first frame:
 * before React exists, before the stylesheet's tokens are applied, when the operator has nothing but the colour
 * of the window to read. `src/design/ThemeContext.tsx` answers the same question -- stored theme, then
 * `prefers-color-scheme`, then dark -- in TypeScript, and the two answers are kept in step by a vitest guard
 * that runs both.
 *
 * What that guard cannot see is the served shell: `vite build` writes a new `index.html`, the gateway injects
 * its canary into it, and an inline script that survives in the source can still fail to survive to the
 * browser. This spec therefore asks the bundle itself, in a real browser, with the module scripts blocked so
 * that only the shell has run, and then again with them served. The two answers have to be the same bytes:
 * a shell that paints one theme and mounts another is a flash of the wrong palette on every cold start, and the
 * rule for which theme is right is stated nowhere here -- it is read off the app, so a rule that moves in the
 * module moves this claim with it instead of failing against a remembered copy.
 */

const COMBINATIONS: (string | null)[] = [null, "light", "dark", "midnight", "auto"];

async function shellAndApp(browser: Browser, colorScheme: "light" | "dark", stored: string | null) {
  const context = await browser.newContext({ colorScheme });
  try {
    const page = await context.newPage();
    // A same-origin page with no scripts, to put the stored theme in place before the shell reads it.
    await page.goto("/favicon.svg");
    await page.evaluate((value) => {
      if (value === null) localStorage.removeItem("raven-theme");
      else localStorage.setItem("raven-theme", value);
    }, stored);

    await page.route("**/assets/**", (route) => route.abort());
    await page.goto("/");
    const painted = {
      theme: await page.getAttribute("html", "data-theme"),
      color: await page.getAttribute('meta[name="theme-color"]', "content"),
    };
    await page.unroute("**/assets/**");

    await page.goto("/");
    await expect(page.locator("#root")).not.toBeEmpty();
    const settled = {
      theme: await page.getAttribute("html", "data-theme"),
      color: await page.getAttribute('meta[name="theme-color"]', "content"),
    };
    return { painted, settled };
  } finally {
    await context.close();
  }
}

test.describe("the first frame of the console", () => {
  for (const colorScheme of ["light", "dark"] as const) {
    for (const stored of COMBINATIONS) {
      const label = `stored ${stored ?? "nothing"}, system prefers ${colorScheme}`;

      test(`is already the theme the app mounts: ${label}`, async ({ browser }) => {
        const { painted, settled } = await shellAndApp(browser, colorScheme, stored);

        // Both null would compare equal, which is how a shell with no script at all would pass.
        expect(painted.theme, `${label}: the served shell set no data-theme before the bundle ran`).not.toBeNull();
        expect(painted.color, `${label}: the served shell set no theme-color`).not.toBeNull();
        expect(settled.theme, `${label}: the app never wrote data-theme`).not.toBeNull();

        expect(painted.theme, `${label}: the shell painted ${painted.theme} and the app mounted ${settled.theme}`).toBe(
          settled.theme,
        );
        expect(
          painted.color,
          `${label}: the shell announced ${painted.color} and the app ${settled.color}`,
        ).toBe(settled.color);
      });
    }
  }
});
