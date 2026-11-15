import { expect, test } from "@playwright/test";

import { signIn, stubGatewaySocket, stubSessions } from "./support";

test.describe("Chat", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("chat page loads with the composer ready once the socket opens", async ({ page }) => {
    await stubGatewaySocket(page);
    await stubSessions(page, ["e2e-session"], "e2e-session");
    await page.goto("/chat");

    await expect(page.getByRole("heading", { name: /chat/i })).toBeVisible();
    await expect(page.getByLabel("Session")).toHaveValue("e2e-session");
    await expect(page.getByPlaceholder(/Enter to send/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();
    await expect(page.getByText("Online", { exact: true })).toBeVisible();
  });

  test("the composer waits for the gateway instead of accepting input", async ({ page }) => {
    // No socket stub: this is the state a console opened against a stopped gateway shows. Before this
    // file could reach it at all, the token was written under a key the app never reads.
    await stubSessions(page, [], null);
    await page.goto("/chat");

    const composer = page.getByPlaceholder(/Connecting to the server/i);
    await expect(composer).toBeVisible();
    await expect(composer).toBeDisabled();
    await expect(page.getByText("Offline", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  test("a message goes out over the socket and the reply lands in the transcript", async ({ page }) => {
    await stubGatewaySocket(page);
    await stubSessions(page, ["e2e-session"], "e2e-session");
    await page.goto("/chat");

    const composer = page.getByPlaceholder(/Enter to send/i);
    await composer.fill("Hello Raven");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(page.getByText("echo: Hello Raven").first()).toBeVisible();
    await expect(composer).toHaveValue("");
  });

  test("a session the gateway cannot create is reported, not swallowed", async ({ page }) => {
    await stubGatewaySocket(page);
    await stubSessions(page, [], null);
    await page.goto("/chat");

    await page.getByRole("button", { name: "New" }).click();
    await expect(page.getByText(/Failed to create session/i)).toBeVisible();
  });

  test("a session the gateway creates becomes the selected one", async ({ page }) => {
    await stubGatewaySocket(page);
    await stubSessions(page, [], "brand-new-session");
    await page.goto("/chat");

    await expect(page.getByLabel("Session")).toHaveCount(0);
    await page.getByRole("button", { name: "New" }).click();
    await expect(page.getByLabel("Session")).toHaveValue("brand-new-session");
  });
});
