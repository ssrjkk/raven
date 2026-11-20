import { expect, test } from "@playwright/test";

import { analyticsFull, metrics, monitorList, status, systemStatus } from "./fixtures/api";
import { healthOk } from "./fixtures/health";
import { signIn, stubApi, stubGatewaySocket } from "./support";

/**
 * The analytics charts are painted from the payload the server actually answers.
 *
 * `web/e2e/fixtures/api.ts` is generated from the routers, so the numbers below are the gateway's contract --
 * and until this file nothing on the browser side ever looked at what `/analytics` does with them. Three
 * defects lived in that blind spot at once, with a green suite: the tool charts were fed metric keys and asked
 * to shorten a prefix they do not start with, the latency cards were titled with the whole collector key, and
 * every colour a chart paints is handed to recharts as `var(--dt-…)` inside an SVG presentation attribute,
 * which either resolves to the theme or silently paints the library's own default -- and no token table or
 * type checker can see which of the two a reader got. Readability itself is `design-devices.spec.ts`'s sweep.
 */
const HEALTHY_API: Record<string, unknown> = {
  "/api/health": healthOk,
  "/api/status": status,
  "/api/admin/system/status": systemStatus,
  "/api/metrics": metrics,
  "/api/monitor/list": monitorList,
  "/api/analytics/full": analyticsFull,
};

/** The spelling the collector stores, which no chart may show a reader. */
const COLLECTOR_SPELLING = ["{", "}", "raven_", "_total"];

interface Paint {
  /** Each chart container, its accessible name and the colours its series is really painted with. */
  charts: { name: string; surfaces: number; drawn: number; strokes: string[]; fills: string[] }[];
  /** The computed colour and text of every axis tick, legend entry and slice label. */
  labels: { text: string; fill: string }[];
  /** What an unresolvable `var()` answers on an SVG node, taken from a planted sentinel. */
  unresolved: { stroke: string; fill: string };
  /** Every colour the active theme publishes, resolved. */
  tokens: string[];
}

async function openAnalytics(page: import("@playwright/test").Page): Promise<void> {
  await signIn(page);
  await stubApi(page, HEALTHY_API);
  await stubGatewaySocket(page);
  await page.goto("/analytics");
  await expect(page.locator(".page-title")).toBeVisible();
  await page.waitForSelector(".recharts-surface", { timeout: 15_000 });
}

async function paint(page: import("@playwright/test").Page): Promise<Paint> {
  return page.evaluate(() => {
    const sentinel = document.createElementNS("http://www.w3.org/2000/svg", "path");
    sentinel.setAttribute("stroke", "var(--dt-colors-no-such-token)");
    sentinel.setAttribute("fill", "var(--dt-colors-no-such-token)");
    document.body.appendChild(sentinel);
    const fallback = getComputedStyle(sentinel);
    const unresolved = { stroke: fallback.stroke, fill: fallback.fill };
    sentinel.remove();

    // The names of the published scale are one thing and the colour a reader gets is another: the token
    // answers `#4d4660` and the painted node answers `rgb(77, 70, 96)`, so the set is taken through the
    // engine's own resolution rather than by string comparison.
    const names = new Set<string>();
    const walk = (rules: CSSRuleList): void => {
      for (const rule of Array.from(rules)) {
        // A theme publishes its scale inside `@layer`, so a walk that stops at the top level finds no names
        // and then reports every colour on the page as unpublished.
        if ("cssRules" in rule && rule.cssRules) walk(rule.cssRules);
        for (const name of Array.from(rule.style || [])) if (name.startsWith("--dt-colors-")) names.add(name);
      }
    };
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        walk(sheet.cssRules);
      } catch {
        // A cross-origin sheet answers nothing; the app's own stylesheet is same-origin.
      }
    }
    const active = getComputedStyle(document.documentElement);
    const swatch = document.createElement("span");
    swatch.style.visibility = "hidden";
    document.body.appendChild(swatch);
    const tokens = new Set<string>();
    for (const name of names) {
      if (!active.getPropertyValue(name).trim()) continue;
      swatch.style.color = `var(${name})`;
      tokens.add(getComputedStyle(swatch).color);
    }
    swatch.remove();

    const charts = Array.from(document.querySelectorAll("figure[role='img']")).map((figure) => {
      const strokes: string[] = [];
      const fills: string[] = [];
      for (const node of Array.from(figure.querySelectorAll("path, rect"))) {
        // A node inside <defs> is a clip path or a mask: it carries a paint and shows none of it.
        if (node.closest("defs")) continue;
        const style = getComputedStyle(node);
        if (style.stroke !== "none") strokes.push(style.stroke);
        if (style.fill !== "none") fills.push(style.fill);
      }
      return {
        name: figure.getAttribute("aria-label") ?? "",
        surfaces: figure.querySelectorAll(".recharts-surface").length,
        drawn: figure.querySelectorAll(".recharts-curve, .recharts-rectangle, .recharts-sector").length,
        strokes,
        fills,
      };
    });

    const labels = Array.from(document.querySelectorAll(".recharts-text")).map((node) => ({
      text: node.textContent?.trim() ?? "",
      fill: getComputedStyle(node).fill,
    }));

    return { charts, labels, unresolved, tokens: [...tokens] };
  });
}

/** The label the gateway's own parts make, composed here from the payload rather than remembered. */
function metricLabel(parts: { family: string; stat: string; labels: Record<string, string | undefined> }): string {
  const values = Object.values(parts.labels).filter((value): value is string => Boolean(value));
  const identity = values.filter((value) => !values.some((other) => other !== value && other.includes(value)));
  return [parts.family, ...identity, parts.stat].filter(Boolean).join(" · ");
}

test.describe("the analytics page paints its charts from the server's payload", () => {
  test("a chart the payload fills is drawn, not just titled", async ({ page }) => {
    await openAnalytics(page);
    const measured = await paint(page);
    expect(measured.charts.length, "no chart container reached the page").toBeGreaterThan(0);
    expect(
      measured.charts.filter((chart) => chart.name === "").map((chart) => chart.surfaces),
      "a chart announces itself as an empty region",
    ).toEqual([]);
    expect(
      measured.charts.filter((chart) => chart.surfaces === 0).map((chart) => chart.name),
      "a chart card holds no drawing surface",
    ).toEqual([]);
    // A chart fed an empty array still paints its axes over blank paper, which is the state the gateway was in
    // while the analytics queries missed their own metric names.
    const blank = measured.charts.filter((chart) => chart.drawn === 0).map((chart) => chart.name);
    expect(blank, `these charts drew nothing: ${blank.join(", ")}`).toEqual([]);
  });

  test("the latency cards are named by the series, not by the key", async ({ page }) => {
    await openAnalytics(page);
    const titles = (analyticsFull.last_hour?.latency_series ?? []).map((series) => metricLabel(series));
    expect(titles.length, "the fixture carries no latency series, so this proves nothing").toBeGreaterThan(0);
    const names = await page.locator("figure[role='img']").evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("aria-label") ?? ""),
    );
    for (const title of titles) expect(names).toContain(title);
  });

  test("a series is painted with a colour the theme publishes", async ({ page }) => {
    await openAnalytics(page);
    const measured = await paint(page);
    const tokens = new Set(measured.tokens);
    expect(tokens.size, "no theme token was read, so this proves nothing").toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const chart of measured.charts) {
      for (const colour of [...chart.strokes, ...chart.fills]) {
        // An unresolved `var()` answers exactly what the planted sentinel answered, so recharts' own default
        // grey is caught by the same comparison rather than by a remembered colour.
        if (colour === measured.unresolved.stroke || colour === measured.unresolved.fill || !tokens.has(colour)) {
          offenders.push(`${chart.name}: ${colour}`);
        }
      }
    }
    expect(offenders, `painted in a colour no token answers:\n  ${[...new Set(offenders)].join("\n  ")}`).toEqual([]);
  });

  test("an axis label is painted with a colour the theme publishes", async ({ page }) => {
    await openAnalytics(page);
    const measured = await paint(page);
    const tokens = new Set(measured.tokens);
    const offenders = measured.labels
      .filter((label) => label.text !== "")
      .filter((label) => label.fill === measured.unresolved.fill || !tokens.has(label.fill))
      .map((label) => `"${label.text}" painted ${label.fill}`);
    expect(offenders, `a label nobody would read:\n  ${[...new Set(offenders)].join("\n  ")}`).toEqual([]);
  });

  test("no chart asks the reader to parse a metric key", async ({ page }) => {
    await openAnalytics(page);
    const measured = await paint(page);
    const onScreen = [
      ...measured.charts.map((chart) => chart.name),
      ...measured.labels.map((label) => label.text),
      ...(await page.locator("figure[role='img'] h2").allInnerTexts()),
    ];
    for (const fragment of COLLECTOR_SPELLING) {
      const offenders = onScreen.filter((text) => text.includes(fragment));
      expect(
        offenders,
        `the collector's own spelling "${fragment}" reached the reader in: ${offenders.join(", ")}`,
      ).toEqual([]);
    }
  });

  test("the metric table answers the names the API was asked for", async ({ page }) => {
    // Chart labels are decomposed; the table is where the exact key belongs, because it is what
    // `/api/analytics/series/{metric_name}` is called with. Both claims are measured, neither by the other.
    await openAnalytics(page);
    const expected = (analyticsFull.summary?.metrics ?? []).map((metric) => metric.name);
    expect(expected.length, "the fixture carries no metrics, so this proves nothing").toBeGreaterThan(0);
    const rows = await page.locator("table tbody tr td:first-child").allInnerTexts();
    for (const name of expected) expect(rows).toContain(name);
  });

  test("the tool charts name the tools the gateway counted", async ({ page }) => {
    await openAnalytics(page);
    const tools = (analyticsFull.tool_usage ?? []).map((tool) => tool.name);
    expect(tools.length, "the fixture carries no tool usage, so this proves nothing").toBeGreaterThan(0);
    const painted = (await page.locator(".recharts-text").allInnerTexts()).join(" ");
    const missing = tools.filter((tool) => !painted.includes(tool.slice(0, 17)));
    expect(missing, `no slice or bar is labelled with these tools: ${missing.join(", ")}`).toEqual([]);
  });
});
