import { expect, type Page, test } from "@playwright/test";

import { metrics, status, systemStatus } from "./fixtures/api";
import { healthOk } from "./fixtures/health";
import { signIn, stubApi } from "./support";

/**
 * Refuse `/api/health` the way `rate_limit_middleware` does, then answer it, and count what the client sent.
 *
 * `waits` carries the `Retry-After` for each refusal — `null` writes no header, which is what a refusal that
 * named no wait looks like. The count is the assertion: whether the console came back, sat down for a minute,
 * or gave up is decided by how many requests the built bundle makes, and only the network shows that.
 */
async function refuseHealth(page: Page, waits: (number | null)[], then: unknown): Promise<() => number> {
  let seen = 0;
  await page.route("**/api/health", (route) => {
    const index = seen;
    seen += 1;
    if (index >= waits.length) {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(then) });
    }
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (waits[index] !== null) headers["retry-after"] = String(waits[index]);
    return route.fulfill({
      status: 429,
      headers,
      body: JSON.stringify({ error: "Too many requests", retry_after: waits[index] }),
    });
  });
  return () => seen;
}

/**
 * Hold until the page has been refused `count` times, then let it sit past the moment a further retry would
 * have landed. A negative claim about requests has no event to await, so the settle carries it: it has to outlast
 * whatever wait a client might be sitting out, and counting in the route handler rather than through a response
 * waiter keeps the first refusal from racing past the test.
 */
async function settleAfterRefusals(page: Page, calls: () => number, count: number, settleMs: number): Promise<void> {
  await expect.poll(calls, { timeout: 10_000 }).toBeGreaterThanOrEqual(count);
  await page.waitForTimeout(settleMs);
}

test.describe("a gateway that refuses for budget", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
    // Registered first so the health route wins it: Playwright consults routes newest-first.
    await stubApi(page, {
      "/api/admin/system/status": systemStatus,
      "/api/status": status,
      "/api/metrics": metrics,
    });
  });

  test("comes back when the refusal said the slot was about to open", async ({ page }) => {
    const calls = await refuseHealth(page, [1], healthOk);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Health Checks" })).toBeVisible();
    expect(calls()).toBe(2);
  });

  test("does not sit out a wait the request is not worth", async ({ page }) => {
    // Six seconds is one past the client's bound, so this is the boundary itself: a client that obeyed any
    // number the header carried would send its second request before the eight-second settle ends, and the
    // console would show data the gateway had refused to give it.
    const calls = await refuseHealth(page, [6], healthOk);
    await page.goto("/");

    await settleAfterRefusals(page, calls, 1, 8_000);
    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Health Checks" })).toHaveCount(0);
    expect(calls()).toBe(1);
  });

  test("keeps the one retry it promised and reports the refusal after it", async ({ page }) => {
    const calls = await refuseHealth(page, [1, 1], healthOk);
    await page.goto("/");

    await settleAfterRefusals(page, calls, 2, 3_000);
    await expect(page.getByRole("heading", { name: "Health Checks" })).toHaveCount(0);
    expect(calls()).toBe(2);
  });

  test("does not invent a wait the refusal never named", async ({ page }) => {
    const calls = await refuseHealth(page, [null], healthOk);
    await page.goto("/");

    await settleAfterRefusals(page, calls, 1, 3_000);
    await expect(page.getByRole("heading", { name: "Health Checks" })).toHaveCount(0);
    expect(calls()).toBe(1);
  });
});
