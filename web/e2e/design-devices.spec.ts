import { expect, type Page, test } from "@playwright/test";

import { analyticsFull, metrics, monitorList, status, systemStatus } from "./fixtures/api";
import { healthOk } from "./fixtures/health";
import { signIn, stubApi } from "./support";

/**
 * The console is held to the storefront's own visual contract.
 *
 * `tests/test_site_app_parity.py` compares the two palettes as published values, and a token scale can
 * agree byte for byte while the page still reads differently: the storefront's panels are translucent so
 * the ambient glow shows through them, its cards answer the cursor, its page is photographed through a
 * grain, and its violet is the light one because the dark one is a button, not a sentence. None of that
 * is visible to a token comparison, and all of it is visible to a reader who has just looked at the site.
 *
 * So this spec measures what a browser computes. Contrast is taken against the background the element
 * actually sits on -- the ancestor paint chain with each `color-mix` and gradient stop resolved the way
 * the engine resolves it -- because the flattened value a stylesheet declares is not the value a reader
 * sees, and a translucent card over a dark page is exactly the case a declared colour hides.
 */

const ROUTES = ["/", "/monitors", "/settings", "/analytics"] as const;
const THEMES = ["dark", "midnight", "light"] as const;

/** The floors the product declares: 4.5:1 for reading text, 3:1 for the large type it sets instead. */
const AA_TEXT = 4.5;
const AA_LARGE = 3.0;

/** `--dt-colors-accent-default` is the button surface. Painted as ink it measures 3.94:1 on the dark
 *  page and 2.9:1 on the violet wash it usually sits on, which is why the storefront keeps a separate
 *  `--dt-colors-text-link` for reading in the brand colour. */
const FILL_ROLES = ["accent-default", "accent-hover", "accent-active"] as const;

type Ink = {
  where: string;
  text: string;
  size: number;
  measured: number;
  floor: number;
  role: string | null;
  ink: string;
  ground: string;
};

type Survey = {
  ink: Ink[];
  cards: number;
  cardGlass: boolean;
  cardHighlight: boolean;
  cardWash: boolean;
  cardPosition: string | null;
  grain: boolean;
  sheen: boolean;
  eyebrowRule: boolean;
  ambientVisible: boolean;
};

type Rgb = { r: number; g: number; b: number; a: number };

function survey(options: { fillNames: string[]; aaText: number; aaLarge: number }): Survey {
  const parse = (value: string | null): Rgb | null => {
    const found = /rgba?\(([^)]+)\)/.exec(value || "");
    if (!found) return null;
    const [r, g, b, a] = found[1].split(",").map((part) => Number.parseFloat(part.trim()));
    return { r, g, b, a: a === undefined ? 1 : a };
  };
  const over = (front: Rgb, back: Rgb): Rgb => {
    if (front.a >= 1) return front;
    return {
      r: front.r * front.a + back.r * (1 - front.a),
      g: front.g * front.a + back.g * (1 - front.a),
      b: front.b * front.a + back.b * (1 - front.a),
      a: 1,
    };
  };
  const channel = (unit: number) => (unit / 255 <= 0.03928 ? unit / 255 / 12.92 : ((unit / 255 + 0.055) / 1.055) ** 2.4);
  const luminance = (rgb: Rgb) => 0.2126 * channel(rgb.r) + 0.7152 * channel(rgb.g) + 0.0722 * channel(rgb.b);
  const ratio = (one: Rgb, two: Rgb) => {
    const first = luminance(one);
    const second = luminance(two);
    return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
  };
  const hex = (rgb: Rgb) => `#${[rgb.r, rgb.g, rgb.b].map((unit) => Math.round(unit).toString(16).padStart(2, "0")).join("")}`;

  /**
   * How much of this element's own paint survives to the screen: its `opacity` and every ancestor's, since
   * an ancestor's fade applies to the whole subtree it contains. A label declared `#000` inside a panel
   * held at 0.6 is not black ink on the panel's ground -- it is black ink *and* the panel's ground, both
   * laid over whatever is behind them, which is a different pair of colours and a lower ratio than the one
   * the stylesheet appears to promise. Measured without this, the fade only ever showed up as a screenshot.
   */
  const fadedBy = (element: Element): number => {
    let total = 1;
    for (let node: Element | null = element; node; node = node.parentElement) {
      total *= Number.parseFloat(getComputedStyle(node).opacity || "1");
    }
    return total;
  };

  /** The one exemption WCAG 1.4.3 writes down: text that belongs to an inactive component has no contrast
   *  minimum. A disabled control is dimmed deliberately -- `.btn-primary:disabled` holds the whole button at
   *  0.55 -- and folding that fade in measures a label no reader is being asked to read. Only the HTML
   *  disabled state counts, so the exemption cannot pay for itself by dropping faded text in general. */
  const inactive = (element: Element): boolean => !!element.closest("[disabled], fieldset[disabled]");

  /** The colour a reader actually sees behind an element: its own paint and each ancestor's, bottom up. */
  const groundOf = (element: Element): Rgb => {
    const stack: Rgb[] = [];
    for (let node: Element | null = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      const fade = fadedBy(node);
      // A gradient's first resolved stop is what sits under the label at the top-left of the panel, and
      // the engine has already substituted every `var()` and `color-mix()` inside it.
      const stop = parse(style.backgroundImage && style.backgroundImage !== "none" ? style.backgroundImage : null);
      if (stop) stack.push({ ...stop, a: stop.a * fade });
      const colour = parse(style.backgroundColor);
      if (colour && colour.a > 0) stack.push({ ...colour, a: colour.a * fade });
      // Only a layer the reader sees at full strength ends the walk: a panel at 0.6 alpha, opaque or
      // otherwise, still lets the page under it speak through the label.
      if (colour && colour.a >= 1 && fade >= 1) break;
    }
    let ground: Rgb = { r: 255, g: 255, b: 255, a: 1 };
    for (const paint of stack.reverse()) ground = over(paint, ground);
    return ground;
  };

  const pathOf = (element: Element): string => {
    const parts: string[] = [];
    for (let node: Element | null = element; node && node.tagName !== "BODY" && parts.length < 3; node = node.parentElement) {
      const named = `${node.getAttribute("class") || ""}`
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .join(".");
      parts.unshift(node.tagName.toLowerCase() + (named ? `.${named}` : ""));
    }
    return parts.join(" > ");
  };

  const root = getComputedStyle(document.documentElement);
  const fills = new Map(
    options.fillNames.map((name) => {
      const probe = document.createElement("span");
      probe.style.color = root.getPropertyValue(`--dt-colors-${name}`).trim();
      document.body.appendChild(probe);
      const resolved = getComputedStyle(probe).color;
      probe.remove();
      return [resolved, `--dt-colors-${name} used as ink`] as [string, string];
    }),
  );

  const ink: Ink[] = [];
  const seen = new Set<string>();
  for (const element of Array.from(document.querySelectorAll("body *"))) {
    if (element.children.length > 0) continue;
    const text = (element.textContent || "").trim();
    if (!text) continue;
    const box = element.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) continue;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden") continue;
    if (inactive(element)) continue;
    // Recharts paints its axis ticks and pie labels with the `fill` attribute and sets nothing on `color`,
    // so the CSS colour of a chart label is whatever the page hands down -- the console's own body ink, at a
    // ratio the tick never reaches. Measuring `color` there reports a label the reader cannot see as one they
    // can, which is the difference between a chart gate and a chart gate that always agrees.
    const declared = element instanceof SVGTextContentElement ? style.fill : style.color;
    const colour = parse(declared);
    // A gradient-clipped headline carries a transparent ink by design; the ramp it paints with belongs
    // to the sheet, and the readable-violet rule below is what holds that ramp to the floor.
    if (!colour || /text/.test(`${style.webkitBackgroundClip}${style.backgroundClip}`)) continue;
    // The ink the screen receives, not the one the rule declares: an alpha written into the colour and a
    // fade inherited from an ancestor are the same event to a reader, and both have to be composited onto
    // the ground before a ratio means anything.
    const painted: Rgb = { ...colour, a: colour.a * fadedBy(element) };
    // Under this it is a skeleton row or an entrance still on its way in, not a sentence to be read.
    if (painted.a < 0.15) continue;
    const size = Number.parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700);
    const ground = groundOf(element);
    const lit = over(painted, ground);
    const measured = ratio(lit, ground);
    const role = fills.get(declared) || null;
    const key = `${pathOf(element)}|${text.slice(0, 12)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const floor = role ? options.aaText : large ? options.aaLarge : options.aaText;
    if (measured < floor || role) {
      ink.push({
        where: pathOf(element),
        text: text.slice(0, 24),
        size,
        measured: Number(measured.toFixed(2)),
        floor,
        role,
        ink: hex(lit),
        ground: hex(ground),
      });
    }
  }

  const card = document.querySelector(".card, .stat-card, .card-bordered");
  const cardStyle = card ? getComputedStyle(card) : null;
  const grain = getComputedStyle(document.body, "::after");
  const heading = document.querySelector(".page-title");
  const eyebrow = document.querySelector(".nav-section-label");
  const main = document.querySelector("main");
  return {
    ink,
    cards: document.querySelectorAll(".card, .stat-card, .card-bordered").length,
    cardGlass:
      !!cardStyle && /linear-gradient/.test(cardStyle.backgroundImage) && cardStyle.backgroundColor === "rgba(0, 0, 0, 0)",
    cardHighlight: !!cardStyle && /inset/.test(cardStyle.boxShadow),
    cardWash: !!card && /radial-gradient/.test(getComputedStyle(card, "::before").backgroundImage),
    cardPosition: cardStyle ? cardStyle.position : null,
    grain: grain.backgroundImage.includes("feTurbulence") && Number(grain.opacity) > 0,
    sheen:
      !!heading &&
      /linear-gradient/.test(getComputedStyle(heading).backgroundImage) &&
      /sheen/.test(getComputedStyle(heading).animationName),
    eyebrowRule: !!eyebrow && Number.parseFloat(getComputedStyle(eyebrow, "::before").width) > 4,
    ambientVisible: !!main && getComputedStyle(main).backgroundColor === "rgba(0, 0, 0, 0)",
  };
}

async function open(page: Page, theme: string, path: string): Promise<Survey> {
  await page.addInitScript(([name, value]) => window.localStorage.setItem(name, value), ["raven-theme", theme]);
  await signIn(page);
  await stubApi(page, {
    "/api/status": status,
    "/api/health": healthOk,
    "/api/admin/system/status": systemStatus,
    "/api/monitor/list": monitorList,
    "/api/metrics": metrics,
    "/api/analytics/full": analyticsFull,
  });
  await page.goto(path);
  // The sheet's devices are only worth measuring on a page that has finished becoming itself; measuring
  // the skeleton instead reports an empty console and blames the theme for it.
  await page.waitForSelector(".page-title", { timeout: 15_000 });
  await page
    .waitForFunction(() => document.querySelectorAll(".card, .stat-card, .card-bordered").length > 0, null, { timeout: 5_000 })
    .catch(() => null);
  // The fold reads opacity at the instant of the sweep, so an entrance still on its way in would be measured
  // as a contrast failure that resolves one frame later. The infinite animations are excluded: the typing
  // dot, the skeleton shimmer and the heading's sheen never settle, and none of them carries a sentence.
  await page
    .waitForFunction(
      () =>
        document.getAnimations().every((animation) => {
          const effect = animation.effect as KeyframeEffect | null;
          return animation.playState !== "running" || effect?.getComputedTiming().iterations === Infinity;
        }),
      null,
      { timeout: 5_000 },
    )
    .catch(() => null);
  return page.evaluate(survey, { fillNames: [...FILL_ROLES], aaText: AA_TEXT, aaLarge: AA_LARGE });
}

const report = (rows: Ink[]) =>
  rows
    .map(
      (row) =>
        `  ${row.measured}:1 (floor ${row.floor}) ${row.size}px ink ${row.ink} on ${row.ground} ${row.role || ""} ` +
        `${row.where} "${row.text}"`,
    )
    .join("\n");

/** Markup planted on the running page so the detector can be measured on a pair whose arithmetic is known. */
type Probe = { label: string; markup: string };

/**
 * Plant the probes, sweep the page with the shipped detector, answer for each label what it measured.
 *
 * The markup rides on the document the console is already running -- not on a page built for the occasion --
 * so a clean sweep says the arithmetic survives the real theme, the real `body` ink and the real stylesheet.
 * `{{label}}` is what the row is filtered by afterwards, so each probe has to carry one.
 */
async function measure(page: Page, probes: Probe[], floors: { aaText: number; aaLarge: number }): Promise<Ink[][]> {
  await page.evaluate(
    (plants) => {
      document.querySelectorAll(".probe-plate").forEach((node) => node.remove());
      for (const plant of plants) {
        const plate = document.createElement("div");
        plate.className = "probe-plate";
        plate.innerHTML = plant.markup.replaceAll("{{label}}", plant.label);
        document.body.appendChild(plate);
      }
    },
    probes,
  );
  // Sent the way every other survey in this file is, so the arithmetic under test is the one the spec ships
  // and not a second copy written here that could pass while the shipped one is wrong.
  const found = await page.evaluate(survey, { fillNames: [...FILL_ROLES], ...floors });
  await page.evaluate(() => document.querySelectorAll(".probe-plate").forEach((node) => node.remove()));
  return probes.map((probe) => found.ink.filter((ink) => ink.text === probe.label));
}

/** The ratios the probes were measured at, which is all most assertions here need. */
const ratios = (rows: Ink[][]) => rows.map((probe) => probe.map((ink) => ink.measured));

/**
 * Every value a given property is declared with, read out of the stylesheet the browser actually loaded.
 *
 * Splitting the text on `;`/`{`/`}` boundaries is how these two rules were written first, and the build
 * minifies so tightly that each chunk keeps the punctuation *in front of* the declaration: `;box-shadow:…`
 * matches no anchored pattern, both scans returned an empty list, and the gates went quiet and green.
 * Pulling the values straight out of the whole text cannot read nothing without saying so, and each
 * caller asserts on how many it found.
 */
async function shippedDeclarations(page: Page, propertySource: string): Promise<string[]> {
  return page.evaluate(async (source) => {
    const links = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]'));
    const sheet = (await Promise.all(links.map((link) => fetch(link.href).then((response) => response.text())))).join("\n");
    const scan = new RegExp(`${source}\\s*:\\s*([^;{}]*)`, "gi");
    const values: string[] = [];
    let match: RegExpExecArray | null;
    while ((match = scan.exec(sheet)) !== null) values.push(match[1].trim());
    return values;
  }, propertySource);
}

/**
 * Every surface the console has, read out of the artifact the browser actually ran.
 *
 * The route list lives in the router, not here: a page that gains a route joins the sweep without this file
 * changing, which is what a remembered list cannot promise. It is taken from the loaded chunk rather than from
 * `src/App.tsx` for the same reason the rest of this spec measures the DOM instead of the stylesheet — the
 * bundle is what the reader gets, and esbuild writes these strings with backticks, so either quoting counts.
 * The floor at the call site is what notices a scan that read nothing: parsing that returns an empty list
 * would otherwise sweep zero surfaces and report a clean console.
 */
async function consoleRoutes(page: Page): Promise<string[]> {
  const bundle = await page.evaluate(async () => {
    const urls = Array.from(document.querySelectorAll("script[src]")).map((node) => (node as HTMLScriptElement).src);
    return (await Promise.all(urls.map((url) => fetch(url).then((response) => response.text())))).join("\n");
  });
  const scan = /path:\s*(?:"([^"]*)"|`([^`]*)`)/g;
  const routes = new Set<string>();
  let match: RegExpExecArray | null;
  while ((match = scan.exec(bundle)) !== null) {
    const found = match[1] ?? match[2];
    // `*` is the catch-all that renders the not-found card, and a segment that starts with `:` or interpolates
    // is filled by data the test has no way to name; neither is a surface a colour could be missing from.
    if (found === "" || found === "*" || found.startsWith(":") || found.includes("$")) continue;
    routes.add(found === "." ? "/" : found.startsWith("/") ? found : `/${found}`);
  }
  return [...routes];
}

/**
 * Paint properties that still hold a `var()` once the browser has the element.
 *
 * React writes the `style` attribute from whatever the page handed it, so a component that keeps token *names*
 * in a JS map and spreads the map into `style={{…}}` arrives here as a colour no source-level rule can see --
 * the toast did, while the static gate that was written to forbid it reported zero offenders. A custom property
 * is excluded: the theme engine and the pointer light write those, and a value the sheet reads back is the
 * sheet still in charge.
 */
function findTokenPaint(): string[] {
  const offenders: string[] = [];
  for (const element of Array.from(document.querySelectorAll<HTMLElement>("[style]"))) {
    const painted = (element.getAttribute("style") || "")
      .split(";")
      .filter((declaration) => !/^\s*--/.test(declaration) && /var\(--dt-(?:colors|shadow)/.test(declaration));
    if (!painted.length) continue;
    const classes = `${element.getAttribute("class") || ""}`.split(/\s+/).filter(Boolean).slice(0, 2).join(".");
    offenders.push(`${element.tagName.toLowerCase()}.${classes} ${painted.join(" ").trim().slice(0, 150)}`);
  }
  return offenders;
}

test.describe("the storefront's devices, in the console", () => {
  for (const theme of THEMES) {
    test(`every console route keeps its text readable and its panels glass in ${theme}`, async ({ page }) => {
      for (const path of ROUTES) {
        const result = await open(page, theme, path);
        expect(result.cards, `${path} rendered no card for the glass rule to apply to`).toBeGreaterThan(0);
        expect(result.cardGlass, `${path}: a card painted flat instead of translucent`).toBe(true);
        expect(result.cardHighlight, `${path}: a card with no light along its inner top edge`).toBe(true);
        expect(result.cardWash, `${path}: a card with no pointer wash`).toBe(true);
        expect(result.cardPosition, `${path}: a card that is not the containing block of its own wash`).toBe("relative");
        expect(result.grain, `${path}: the page carries no grain`).toBe(true);
        expect(result.sheen, `${path}: the page title is not lit`).toBe(true);
        expect(result.eyebrowRule, `${path}: the kicker has no rule in front of it`).toBe(true);
        expect(result.ambientVisible, `${path}: an opaque ground is painted over the ambient glow`).toBe(true);
        expect(result.ink, `${path} in ${theme} renders text nobody can read:\n${report(result.ink)}`).toEqual([]);
      }
    });
  }

  test("a card answers the cursor where the pointer actually is", async ({ page }) => {
    await open(page, "dark", "/monitors");
    const card = page.locator(".card, .stat-card, .card-bordered").first();
    await expect(card).toBeVisible();
    const box = await card.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box!.x + box!.width - 12, box!.y + box!.height - 10);
    await expect
      .poll(() => card.evaluate((el) => `${el.style.getPropertyValue("--gx")}|${el.style.getPropertyValue("--gy")}`))
      .toMatch(/^\d+(\.\d+)?px\|\d+(\.\d+)?px$/);
    const [gx, gy] = (await card.evaluate((el) => [el.style.getPropertyValue("--gx"), el.style.getPropertyValue("--gy")])) as [
      string,
      string,
    ];
    expect(Number.parseFloat(gx), "the light followed the cursor to the wrong edge").toBeGreaterThan(box!.width * 0.6);
    expect(Number.parseFloat(gy), "the light followed the cursor to the wrong edge").toBeGreaterThan(box!.height * 0.6);
  });

  test("reduced motion leaves the card alone", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page, "dark", "/monitors");
    const card = page.locator(".card, .stat-card, .card-bordered").first();
    const box = await card.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box!.x + box!.width - 12, box!.y + box!.height - 10);
    await page.waitForTimeout(150);
    expect(await card.evaluate((el) => `${el.style.getPropertyValue("--gx")}|${el.style.getPropertyValue("--gy")}`)).toBe("50%|50%");
  });

  test("the readable violet, not the button violet, is what the sheet paints text with", async ({ page }) => {
    await page.goto("/");
    // `border-color` and `background-color` are fills; the property that paints ink is `color`, and the
    // lookbehind is what keeps those two out of the count.
    const inks = await shippedDeclarations(page, "(?<![-\\w])color");
    expect(inks.length, "the sheet was read but carried no `color` declaration").toBeGreaterThan(50);
    const offenders = inks.filter((value) =>
      /var\(--dt-colors-accent-(default|hover|active)\)|#8452f5|#7c3aed|#6d28d9/i.test(value));
    expect(offenders, `the sheet paints text with a fill role: ${offenders.join(" | ")}`).toEqual([]);
  });

  test("every shadow the sheet asks for is a shadow the engine paints", async ({ page }) => {
    await page.goto("/");
    const shadows = await shippedDeclarations(page, "box-shadow");
    // A token holds a whole shadow, so an offset written in front of it substitutes past the grammar's
    // five components and the declaration is dropped. The CSSOM keeps the text either way, which is why
    // this feeds each value back through the engine and reads what survives.
    const fromTokens = shadows.filter((value) => /--dt-shadow-/.test(value));
    expect(fromTokens.length, "the sheet was read but carries no shadow built from a token").toBeGreaterThan(0);
    const dropped = await page.evaluate((values) => {
      const probe = document.createElement("div");
      document.body.appendChild(probe);
      const bad: string[] = [];
      for (const value of values) {
        probe.style.boxShadow = "";
        probe.style.boxShadow = value;
        if (getComputedStyle(probe).boxShadow === "none") bad.push(value);
      }
      probe.remove();
      return bad;
    }, fromTokens);
    expect(dropped, `these box-shadow declarations compute to none: ${dropped.join(" | ")}`).toEqual([]);
  });

  test("no page hands an element a colour the sheet already publishes", async ({ page }) => {
    // A settled frame for every surface the router names, so the sweep is minutes of navigation and the
    // thirty seconds Playwright gives a test by default is not enough to reach a verdict.
    test.setTimeout(240_000);
    await page.addInitScript(([name, value]) => window.localStorage.setItem(name, value), ["raven-theme", "dark"]);
    await signIn(page);
    await stubApi(page, {
      "/api/status": status,
      "/api/health": healthOk,
      "/api/admin/system/status": systemStatus,
      "/api/monitor/list": monitorList,
      "/api/metrics": metrics,
    });
    await page.goto("/");
    // The route list is read off the chunk this page just ran, so there is a chunk to read before the sweep starts.
    await page.waitForSelector(".page-title", { timeout: 15_000 });
    const routes = await consoleRoutes(page);
    expect(routes.length, "the bundle loaded but named no console routes").toBeGreaterThan(20);
    const offenders: string[] = [];
    for (const route of routes) {
      await page.goto(route);
      // One settled frame per surface: a scan taken while the page is still mounting reads the skeleton and
      // misses the component, and an error a stubbed endpoint raises paints a toast a moment later.
      await page.waitForTimeout(400);
      offenders.push(...(await page.evaluate(findTokenPaint)).map((found) => `${route} ${found}`));
    }
    expect(
      offenders,
      `token colours reached the DOM on ${routes.length} surfaces:\n${offenders.slice(0, 20).join("\n")}`,
    ).toEqual([]);
  });

  test("a fade is folded into the ink and the ground it fades before any ratio is taken", async ({ page }) => {
    // The detector's own planted violations, on colours this test chooses so the arithmetic can be checked
    // against the page: black on white is 21:1, and a reader shown that pair at half strength is not shown
    // 21:1. Measured against the declared colours every faded probe below clears the floor with room to
    // spare, so a spec that ignores `opacity` calls this page correct while the console fades its own labels
    // into the panel behind them -- which is what a translucent card over an ambient glow does constantly.
    // The last two probes hold the one exemption the standard writes down, in both directions: the dimmed
    // control has to be let go, and whatever merely claims to be disabled has to stay on the measurement.
    await open(page, "dark", "/");

    const probes: Probe[] = [
      {
        label: "probe 1 unfaded",
        markup:
          '<div style="background:#ffffff;padding:8px"><span style="color:#000000;font-size:16px">{{label}}</span></div>',
      },
      {
        label: "probe 2 faded",
        markup:
          '<div style="background:#ffffff;padding:8px"><span style="color:#000000;font-size:16px;opacity:0.5">{{label}}</span></div>',
      },
      {
        label: "probe 3 faded",
        markup:
          '<div style="background:#333333;padding:8px"><div style="background:#ffffff;opacity:0.5">' +
          '<span style="color:#000000;font-size:16px">{{label}}</span></div></div>',
      },
      {
        label: "probe 4 faded",
        markup:
          '<div style="background:#ffffff;padding:8px"><button disabled style="background:#7c3aed;padding:4px">' +
          '<span style="color:#000000;font-size:16px;opacity:0.5">{{label}}</span></button></div>',
      },
      {
        label: "probe 5 faded",
        markup:
          '<div style="background:#ffffff;padding:8px"><span aria-disabled="true" style="color:#000000;font-size:16px;opacity:0.5">{{label}}</span></div>',
      },
    ];

    const [uncoloured, halfOnThePage, halfThroughAnAncestor, dimmedControl, claimsDisabled] = ratios(
      await measure(page, probes, { aaText: AA_TEXT, aaLarge: AA_LARGE }),
    );
    // The control: the pair the sheet declares is the pair the reader gets, and it is not a violation.
    expect(uncoloured, "black on white at full strength was reported, so the probes fail for another reason").toEqual([]);
    expect(halfOnThePage, "a 16px label held at 0.5 opacity reaches the screen at 3.98:1 and was let through").toEqual([
      3.98,
    ]);
    expect(
      halfThroughAnAncestor,
      "an ancestor's fade moves the ground as well as the ink: 2.99:1 was let through",
    ).toEqual([2.99]);
    expect(dimmedControl, "a disabled control is exempt from the contrast minimum and was reported anyway").toEqual([]);
    expect(
      claimsDisabled,
      "`aria-disabled` is not the disabled state: a faded label that still answers clicks was let through",
    ).toEqual([3.98]);

    // The same probes at a floor nothing clears, so the arithmetic itself is on the record: a detector that
    // found the rows for the wrong reason would still pass the five assertions above.
    expect(ratios(await measure(page, probes, { aaText: 100, aaLarge: 100 }))).toEqual([
      [21],
      [3.98],
      [2.99],
      [],
      [3.98],
    ]);
  });

  test("a chart label is measured by the fill it paints, not the colour it inherits", async ({ page }) => {
    // recharts hands an axis tick its `fill` attribute and says nothing about `color`, so the CSS colour of a
    // tick is the page's body ink by inheritance. A detector that reads `color` there measures a label nobody
    // paints: it clears 17.4:1 while the 10px grey a reader actually sees does not clear 4.5:1, and the chart
    // pages sit inside a green suite that has never looked at them. Both fill probes are reported for their
    // fill, and would vanish from the sweep rather than measure low if the inherited colour were used.
    await open(page, "dark", "/");

    const probes: Probe[] = [
      {
        label: "probe 1 tick",
        // `#7f7f7f` on `#1a1a1a` is 4.35:1; the body ink this node inherits is white, 17.4:1.
        markup:
          '<div style="background:#1a1a1a;padding:8px"><svg width="140" height="24" style="color:#ffffff">' +
          '<text x="0" y="16" font-size="10" fill="#7f7f7f">{{label}}</text></svg></div>',
      },
      {
        label: "probe 2 greypack",
        // recharts' own fallback ink: a text node handed no fill is painted `#808080`, a grey no theme
        // publishes and no token table can be held to it. 4.41:1 on this ground.
        markup:
          '<div style="background:#1a1a1a;padding:8px"><svg width="140" height="24">' +
          '<text x="0" y="16" font-size="10" fill="#808080">{{label}}</text></svg></div>',
      },
      {
        label: "probe 3 html",
        // The same grey on the side the detector has always read, so the two paths cannot disagree.
        markup:
          '<div style="background:#1a1a1a;padding:8px"><span style="color:#7f7f7f;font-size:10px">{{label}}</span></div>',
      },
    ];

    const rows = await measure(page, probes, { aaText: AA_TEXT, aaLarge: AA_LARGE });
    expect(ratios(rows)).toEqual([[4.35], [4.41], [4.35]]);
    // The pair named on the record, not just its ratio: the fill over the panel it sits on. White over the
    // same panel is what the inherited colour would have answered, and it is 17.4:1 away from this verdict.
    expect(rows.map((probe) => probe.map((ink) => `${ink.ink} on ${ink.ground}`))).toEqual([
      ["#7f7f7f on #1a1a1a"],
      ["#808080 on #1a1a1a"],
      ["#7f7f7f on #1a1a1a"],
    ]);
  });
});
