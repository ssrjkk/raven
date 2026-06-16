import { test, expect } from "@playwright/test";

test.describe("Chat", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("raven_token", "test-token");
    });
  });

  test("chat page loads with session selector", async ({ page }) => {
    await page.goto("/chat");

    await expect(page.getByRole("heading", { name: /chat/i })).toBeVisible();
    await expect(page.getByPlaceholder(/type a message/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /send/i })).toBeVisible();
  });

  test("new session button creates session", async ({ page }) => {
    await page.goto("/chat");

    await page.getByRole("button", { name: /new/i }).click();
    // Wait for session creation
    await page.waitForTimeout(1000);
  });

  test("message input and send button work", async ({ page }) => {
    await page.goto("/chat");

    const input = page.getByPlaceholder(/type a message/i);
    await input.fill("Hello Raven");
    await expect(input).toHaveValue("Hello Raven");

    await page.getByRole("button", { name: /send/i }).click();
  });

  test("shows connection status indicator", async ({ page }) => {
    await page.goto("/chat");

    await expect(page.getByText(/connected|disconnected/i)).toBeVisible();
  });
});
