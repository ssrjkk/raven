import { test, expect } from "@playwright/test";

test.describe("Monitors", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("raven_token", "test-token");
    });
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
