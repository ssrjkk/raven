import { expect, test } from "@playwright/test";

import { metrics, status, systemStatus } from "./fixtures/api";
import { healthDegraded, healthOk } from "./fixtures/health";
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

  test("the cards show what the gateway reports", async ({ page }) => {
    // The payloads are the answers of GET /api/admin/system/status and GET /api/status
    // (scripts/gen_api_fixtures.py), so every number on the page is claimed against what the server sends and
    // not against a literal this file preferred. The card falls back from one route to the other depending on
    // which answered first, so both are stubbed and the two answers are required to agree -- see
    // tests/core/test_spa_api_contract.py.
    await stubApi(page, { "/api/admin/system/status": systemStatus, "/api/status": status, "/api/metrics": metrics });
    await page.goto("/");

    const values = page.locator(".stat-card").locator(".stat-card-value");
    await expect(values.nth(0)).toHaveText(String(systemStatus.channels));
    await expect(values.nth(1)).toHaveText(String(systemStatus.agents));
    await expect(values.nth(2)).toHaveText(String(status.plugins));
    await expect(values.nth(3)).toHaveText(status.model.split("/").pop() ?? "");
  });

  test("health checks render what the gateway answers", async ({ page }) => {
    // The payload is what GET /api/health answered on a live gateway (scripts/gen_health_fixture.py), not a
    // hand-typed stand-in. A hand-typed `{checks: [{name, latency_ms, critical}]}` array — a shape the server
    // has never emitted — kept this spec green while the real payload threw
    // `TypeError: p.checks.map is not a function` and the shipped page fell to its error boundary.
    await stubApi(page, { "/api/health": healthOk });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Health Checks" })).toBeVisible();
    const card = page.getByRole("heading", { name: "Health Checks" }).locator("..");
    for (const name of Object.keys(healthOk.checks)) {
      await expect(card.getByText(name, { exact: true })).toHaveCount(1);
    }
    // Every check here answers an empty `detail`, so each row must show the component's own "ok" — a row
    // printing the raw detail would be blank, which is the state operators actually complained about.
    await expect(card.getByText("ok", { exact: true })).toHaveCount(Object.keys(healthOk.checks).length);
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
  });

  test("a failing check shows the detail the gateway produced", async ({ page }) => {
    await stubApi(page, { "/api/health": healthDegraded });
    await page.goto("/");

    const card = page.getByRole("heading", { name: "Health Checks" }).locator("..");
    await expect(card.getByText("no route to host", { exact: true })).toHaveCount(1);
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
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
