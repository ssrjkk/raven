import { expect, test } from "@playwright/test";

import { monitorList } from "./fixtures/api";
import { signIn, stubApi } from "./support";

test.describe("Monitors", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    // The page polls `/api/monitor/list`; with no gateway behind the preview server that request goes
    // through vite's proxy and prints an ECONNREFUSED aggregate into the run log for every spec. The payload
    // is the answer of the route on an install that has registered its monitors (scripts/gen_api_fixtures.py),
    // so the rows the page builds are the rows the server describes.
    await stubApi(page, { "/api/monitor/list": monitorList });
  });

  test("monitors page loads", async ({ page }) => {
    await page.goto("/monitors");

    await expect(page.getByRole("heading", { name: /monitors/i })).toBeVisible();
  });

  test("navigate to monitors from sidebar", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("link", { name: /monitors/i }).click();
    await expect(page).toHaveURL(/\/monitors/);
    await expect(page.getByRole("heading", { name: /monitors/i })).toBeVisible();
  });
});
