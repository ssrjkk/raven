import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test("login page loads", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: /raven ai/i })).toBeVisible();
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("shows error on invalid login", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel(/username/i).fill("nonexistent");
    await page.getByLabel(/password/i).fill("wrongpassword");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByText(/invalid credentials/i)).toBeVisible();
  });

  test("switches to register form", async ({ page }) => {
    await page.goto("/login");

    await page.getByText(/register/i).click();
    await expect(page.getByText(/create an account/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /register/i })).toBeVisible();
  });

  test("validates required fields", async ({ page }) => {
    await page.goto("/login");

    const usernameInput = page.getByLabel(/username/i);
    const passwordInput = page.getByLabel(/password/i);

    // Both fields should be required
    await expect(usernameInput).toHaveAttribute("required", "");
    await expect(passwordInput).toHaveAttribute("required", "");
  });
});
