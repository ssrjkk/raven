import { test, expect } from "@playwright/test";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    // Set auth token to bypass login
    await page.addInitScript(() => {
      localStorage.setItem("raven_token", "test-token");
    });
  });

  test("dashboard renders with metrics", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    await expect(page.getByText(/channels/i)).toBeVisible();
    await expect(page.getByText(/agents/i)).toBeVisible();
    await expect(page.getByText(/plugins/i)).toBeVisible();
  });

  test("shows health checks section", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText(/health checks/i)).toBeVisible();
  });

  test("shows running status", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByText(/running/i)).toBeVisible();
  });

  test("navigation sidebar is accessible", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("link", { name: /chat/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /monitors/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /tasks/i })).toBeVisible();
  });
});
