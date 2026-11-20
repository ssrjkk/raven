import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { analyticsFull, metrics, monitorList, status, systemStatus } from "./fixtures/api";
import { healthOk } from "./fixtures/health";
import { signIn, stubApi, stubGatewaySocket } from "./support";

/**
 * Every page the console declares, mounted once in a real browser.
 *
 * `App.tsx` routes 39 console pages and the other specs visited four of them, so on the other thirty-five a
 * component that throws in an effect, a screen that paints nothing, or a route that bounces to the not-found
 * card was a green suite and a broken page. The list is read out of the router rather than kept here, so
 * adding a page covers it; `the router in the source is the router the bundle ships` is what notices when
 * the reader below stops understanding the file and starts reporting a passing suite over three pages.
 */
const APP_TSX = readFileSync(fileURLToPath(new URL("../src/App.tsx", import.meta.url)), "utf8");

/** The sign-in form has its own spec and `*` is the not-found screen: neither is a console page. */
const NOT_A_CONSOLE_PAGE = new Set(["/login", "*"]);

interface Route {
  readonly path: string;
  readonly component: string;
}

/**
 * The text of every `<Route>` opening tag, in document order.
 *
 * Matching to the first `/>` reads the wrapper at `App.tsx:58` as a tag that ends inside its first child, so
 * a nested `element={<ProtectedRoute>}` silently swallows routes. Walking with a brace depth is what a JSX
 * opening tag actually needs, and a tag this function cannot close raises instead of being dropped.
 */
function openingTags(source: string): string[] {
  const tags: string[] = [];
  for (const match of source.matchAll(/<Route\b/g)) {
    let index = match.index + "<Route".length;
    let depth = 0;
    while (index < source.length) {
      const char = source[index];
      if (char === "{") depth += 1;
      else if (char === "}") depth -= 1;
      else if (char === ">" && depth === 0) break;
      index += 1;
    }
    if (index >= source.length) throw new Error(`an unclosed <Route> tag in ${APP_TSX.slice(match.index, match.index + 60)}`);
    tags.push(source.slice(match.index, index + 1));
  }
  return tags;
}

function parseRoutes(): { pages: Route[]; skipped: string[] } {
  const pages: Route[] = [];
  const skipped: string[] = [];
  for (const tag of openingTags(APP_TSX)) {
    const component = /element=\{\s*<(\w+)/.exec(tag)?.[1] ?? "anonymous";
    const declared = /path="([^"]*)"/.exec(tag)?.[1];
    const path = declared ?? (/\bindex\b/.test(tag) ? "/" : null);
    if (path === null || NOT_A_CONSOLE_PAGE.has(path) || component === "Login" || component === "NotFound") {
      // The layout wrapper carries an element and no page of its own; a tag with neither is a redirect.
      skipped.push(`${component}@${declared ?? "no path"}`);
      continue;
    }
    pages.push({ path: path.startsWith("/") ? path : `/${path}`, component });
  }
  return { pages, skipped };
}

const { pages: CONSOLE_PAGES, skipped: SKIPPED_ROUTES } = parseRoutes();
const ROUTE_TAGS = (APP_TSX.match(/<Route\b/g) ?? []).length;

/** The answers a healthy gateway gives, so a page reaches its populated state instead of its empty one. */
const HEALTHY_API: Record<string, unknown> = {
  "/api/health": healthOk,
  "/api/status": status,
  "/api/admin/system/status": systemStatus,
  "/api/metrics": metrics,
  "/api/monitor/list": monitorList,
  "/api/analytics/full": analyticsFull,
};

async function openConsolePage(page: import("@playwright/test").Page, path: string): Promise<string[]> {
  const thrown: string[] = [];
  page.on("pageerror", (error) => thrown.push(`${error.message}`));
  await signIn(page);
  await stubApi(page, HEALTHY_API);
  await stubGatewaySocket(page);
  await page.goto(path);
  return thrown;
}

test.describe("the console renders every page it declares", () => {
  test("the route reader saw every route in the router", () => {
    expect(CONSOLE_PAGES.length, "no route was parsed out of App.tsx at all").toBeGreaterThan(0);
    expect(
      CONSOLE_PAGES.length + SKIPPED_ROUTES.length,
      `parsed ${CONSOLE_PAGES.length} pages, skipped ${SKIPPED_ROUTES.join(", ")}`,
    ).toBe(ROUTE_TAGS);
  });

  test("the router in the source is the router the bundle ships", async ({ page }) => {
    // The spec's own reader is checked against what the browser actually loaded: esbuild writes these
    // strings with either quoting, and a reader that stopped matching would shrink this suite silently.
    await openConsolePage(page, "/");
    const bundle = await page.evaluate(async () => {
      const urls = Array.from(document.querySelectorAll("script[src]")).map((node) => node.src);
      return (await Promise.all(urls.map((url) => fetch(url).then((response) => response.text())))).join("\n");
    });
    const shipped = new Set<string>();
    for (const match of bundle.matchAll(/path:\s*(?:"([^"]*)"|`([^`]*)`)/g)) {
      const found = match[1] ?? match[2];
      // A segment the browser fills from data is not a page this spec can navigate to.
      if (!found || found === "*" || found.startsWith(":") || found.includes("$")) continue;
      shipped.add(found === "." ? "/" : found.startsWith("/") ? found : `/${found}`);
    }
    expect(shipped.size, "the scan of the built bundle found no routes, so this proves nothing").toBeGreaterThan(0);
    const opened = new Set([...CONSOLE_PAGES.map((route) => route.path), ...NOT_A_CONSOLE_PAGE]);
    const missing = [...shipped].filter((path) => !opened.has(path));
    expect(missing, `routes the bundle declares that no test opens: ${missing.join(", ")}`).toEqual([]);
  });

  for (const route of CONSOLE_PAGES) {
    test(`${route.path} paints ${route.component}`, async ({ page }) => {
      const thrown = await openConsolePage(page, route.path);
      const main = page.locator("main");
      await expect(main, `${route.path} rendered no content area`).toBeVisible();
      await expect
        .poll(async () => (await main.innerText()).trim().length, {
          message: `${route.path} mounted an empty screen`,
          timeout: 10_000,
        })
        .toBeGreaterThan(0);
      const box = await main.boundingBox();
      expect(box?.height ?? 0, `${route.path} painted a content area with no height`).toBeGreaterThan(80);
      await expect(page, `${route.path} bounced to another route`).toHaveURL(new RegExp(`${route.path}$`));
      await expect(page.getByText("Something went wrong"), `${route.path} hit the error boundary`).toHaveCount(0);
      expect(thrown, `${route.path} threw while mounting: ${thrown.join(" | ")}`).toEqual([]);
    });
  }
});
