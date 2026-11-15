import { expect, test } from "@playwright/test";

import { signIn, stubApi } from "./support";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("dashboard renders its metric cards", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
    await expect(page.locator(".stat-card-label")).toHaveText(["Channels", "Agents", "Plugins", "Model"]);
    await expect(page.getByRole("heading", { name: "Key Metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Flow Sessions" })).toBeVisible();
  });

  test("metrics name the sections they belong to, once each", async ({ page }) => {
    // "Channels" is both a card label and a panel heading, and a bare getByText(/channels/i) resolved
    // to both and failed Playwright's strict mode — which is how this file stayed red for a selector
    // problem rather than a product one.
    await stubApi(page, {});
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Channels" })).toHaveCount(1);
    await expect(page.locator(".stat-card-label", { hasText: "Channels" })).toHaveCount(1);
  });

  test("metrics fall back to a placeholder when the gateway is unreachable", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/");

    await expect(page.locator(".stat-card-value")).toHaveText(["—", "—", "—", "—"]);
  });

  test("metrics show what the gateway reports", async ({ page }) => {
    await stubApi(page, {
      "/api/admin/system/status": { channels: 3, agents: 2, running: true, version: "0.4.8" },
    });
    await page.goto("/");

    const values = page.locator(".stat-card").locator(".stat-card-value");
    await expect(values.nth(0)).toHaveText("3");
    await expect(values.nth(1)).toHaveText("2");
  });

  test("health checks appear when the gateway reports them", async ({ page }) => {
    await stubApi(page, {
      "/api/health": {
        overall: true,
        checks: [
          { name: "database", ok: true, latency_ms: 12.4, critical: false },
          { name: "telegram", ok: false, latency_ms: 0, critical: true },
        ],
      },
    });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Health Checks" })).toBeVisible();
    await expect(page.getByText("database", { exact: true })).toBeVisible();
    await expect(page.getByText("12ms")).toBeVisible();
    await expect(page.getByText("critical", { exact: true })).toBeVisible();
  });

  test("no health panel is invented when the gateway does not answer", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Health Checks" })).toHaveCount(0);
  });

  test("navigation sidebar is accessible", async ({ page }) => {
    await stubApi(page, {});
    await page.goto("/");

    await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Monitors" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Tasks" })).toBeVisible();
  });
});
