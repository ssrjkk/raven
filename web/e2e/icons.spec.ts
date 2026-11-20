import { expect, type Page, test } from "@playwright/test";

/**
 * The brand art the built bundle promises, measured as the browser receives it.
 *
 * The Python guards read the source tree: they know `web/index.html` links `/favicon.svg` and that
 * `web/public` carries the file. Neither of them sees the bundle. This spec runs against `vite preview` over
 * `web/dist` -- the tree the image ships -- and asks for exactly the addresses a browser is told to ask for,
 * so a build step that drops a file, a link that points at a path the bundle does not hold, and a manifest
 * tile whose declared size is not the drawn size all fail here instead of at the operator's tab.
 *
 * A missing icon is not an error anywhere in the product: the browser paints its own globe, the install tile
 * is the generic one, and the console looks perfectly healthy. That is why the claim is made over the network
 * and in the decoder, and not by reading a file.
 *
 * One claim is deliberately not made here: that a link's `type` attribute equals the header the server
 * answers. `vite preview` and the gateway keep separate mime tables and `.ico` is where they part, so that
 * equality is measured over `mount_spa` in `tests/test_spa_public_assets.py` -- against the server that ships.
 */

type Served = { status: number; contentType: string; length: number };

async function fetched(page: Page, href: string): Promise<Served> {
  const response = await page.request.get(href);
  const body = await response.body();
  return { status: response.status(), contentType: response.headers()["content-type"] ?? "", length: body.byteLength };
}

/** Ask the page's own decoder what it got, which is the only answer that says the bytes are a picture. */
async function decodedSize(page: Page, href: string): Promise<{ width: number; height: number } | null> {
  // The decoder lives in the page, so its fetch needs a document to resolve a bundle path against: an
  // un-navigated page is `about:blank`, where every relative URL is unparseable.
  if (page.url() === "about:blank") await page.goto("/");
  return page.evaluate(async (url) => {
    const response = await fetch(url);
    if (!response.ok) return null;
    try {
      const bitmap = await createImageBitmap(await response.blob());
      const size = { width: bitmap.width, height: bitmap.height };
      bitmap.close();
      return size;
    } catch {
      return null;
    }
  }, new URL(href, page.url()).href);
}

test.describe("the icons the bundle ships", () => {
  test("every icon the shell links is a picture the browser is handed", async ({ page }) => {
    await page.goto("/");

    const links = await page.$$eval("link[rel~='icon'], link[rel~='apple-touch-icon']", (nodes) =>
      nodes.map((node) => ({
        rel: node.getAttribute("rel") ?? "",
        href: node.getAttribute("href") ?? "",
        type: node.getAttribute("type") ?? "",
      })),
    );
    expect(links.length, "the shell linked no icon at all").toBeGreaterThanOrEqual(2);

    for (const link of links) {
      expect(link.href, `${link.rel} linked an address the document cannot resolve against`).toMatch(/^\//);
      const got = await fetched(page, link.href);
      expect(got.status, `${link.href} (${link.rel}) is not in the bundle the browser gets`).toBe(200);
      expect(got.contentType, `${link.href} answered ${got.contentType}, which no image decoder reads`).toContain(
        "image/",
      );
      if (link.type) {
        expect(link.type, `${link.href} is announced to the browser as ${link.type}, which is not a picture`).toMatch(
          /^image\//,
        );
      }
      if (!link.href.endsWith(".svg")) {
        // Rasters only: Chromium refuses an svg in `createImageBitmap`, so a vector is claimed by the bytes the
        // shell is handed and by the manifest's size table below, never by this decoder.
        const drawn = await decodedSize(page, link.href);
        expect(drawn, `${link.href} reached the browser as ${got.contentType} and did not decode`).not.toBeNull();
        expect(drawn!.width, `${link.href} is a raster the size of nothing`).toBeGreaterThan(0);
        expect(drawn!.width, `${link.href} is not square`).toBe(drawn!.height);
      }
    }
  });

  test("every install tile the manifest promises is the size it declares", async ({ page }) => {
    const manifest = await (await page.request.get("/manifest.json")).json();
    const tiles: { src: string; sizes: string; type: string }[] = manifest.icons ?? [];
    expect(tiles.length, "manifest.json carried no icons to install").toBeGreaterThanOrEqual(2);

    for (const tile of tiles) {
      const got = await fetched(page, tile.src);
      expect(got.status, `manifest.json promises ${tile.src}, which the bundle does not hold`).toBe(200);
      expect(got.contentType.split(";")[0], `${tile.src} is announced as ${tile.type} and answered otherwise`).toBe(
        tile.type,
      );
      const [width, height] = tile.sizes.split("x").map(Number);
      expect(width, `${tile.src} declares no size`).toBeGreaterThan(0);
      expect(height, `${tile.src} declares a size that is not square`).toBe(width);
      if (tile.type === "image/png") {
        const drawn = await decodedSize(page, tile.src);
        expect(drawn, `${tile.src} did not decode as an image`).not.toBeNull();
        expect(
          drawn,
          `${tile.src} declares ${width}x${height} and the browser decoded ${drawn!.width}x${drawn!.height}`,
        ).toEqual({ width, height });
      }
    }
  });

  test("the offline shell asks for art the bundle carries", async ({ page }) => {
    await page.goto("/offline.html");

    const hrefs = await page.$$eval("link[rel~='icon'], link[rel~='apple-touch-icon']", (nodes) =>
      nodes.map((node) => node.getAttribute("href") ?? ""),
    );
    expect(hrefs.length, "the shell a browser opens with no network linked no icon").toBeGreaterThanOrEqual(2);
    for (const href of hrefs) {
      const got = await fetched(page, href);
      expect(got.status, `the offline shell links ${href}, which the bundle does not hold`).toBe(200);
      expect(got.length, `${href} reached the offline shell as an empty body`).toBeGreaterThan(0);
    }
  });

  test("the worker's precache list is a list of files the bundle holds", async ({ page }) => {
    const worker = await (await page.request.get("/sw.js")).text();
    const listed = [...worker.matchAll(/["'`](\/[^"'`\s]+)["'`]/g)].map((match) => match[1]);
    expect(listed.length, "sw.js precached nothing, so the promise below checks nothing").toBeGreaterThan(5);

    // The list also names built chunks whose hashed names live in the bundle, so only the paths the worker
    // spells out by hand -- the brand art and the fonts -- are claimed here.
    for (const href of listed.filter((path) => /favicon|icon-|manifest/.test(path))) {
      const response = await page.request.get(href);
      expect(response.status(), `sw.js precaches ${href}, which the bundle does not carry`).toBe(200);
    }
  });
});
