import { Page } from "@playwright/test";

/** The key `src/api/client.ts` reads, and reads once: `let _token = localStorage.getItem(TOKEN_KEY)`
 *  runs at import, so the value has to be in storage before the first navigation, not after. */
export const TOKEN_KEY = "raven_auth_token";

export async function signIn(page: Page): Promise<void> {
  await page.addInitScript((key) => {
    window.localStorage.setItem(key, "e2e-token");
  }, TOKEN_KEY);
}

/**
 * Answer `/ws` without a gateway.
 *
 * `useWebSocket` sets `connected` on `onopen`, so accepting the socket is what moves the composer from
 * "Connecting to the server…" to enabled; frames the page sends come back as an assistant reply so the
 * transcript assertion runs against the real encode/decode path rather than a mocked component.
 */
export async function stubGatewaySocket(page: Page): Promise<void> {
  await page.routeWebSocket("**/ws", (route) => {
    route.onMessage((raw) => {
      let frame: { text?: string; session_id?: string };
      try {
        frame = JSON.parse(String(raw));
      } catch {
        return;
      }
      route.send(
        JSON.stringify({
          type: "message",
          role: "assistant",
          content: `echo: ${frame.text ?? ""}`,
          session_id: frame.session_id || "e2e",
        }),
      );
    });
  });
}

/**
 * Serve `routes` for the paths named by pathname and refuse every other `/api` call.
 *
 * Refusing matters: the shipped bundle registers `/sw.js`, and an unstubbed call that reaches the
 * preview server gets index.html back with a 200, which the client then fails to parse — a slower and
 * fuzzier path to the same state.
 */
export async function stubApi(page: Page, routes: Record<string, unknown>): Promise<void> {
  await page.route("**/api/**", (route) => {
    const body = routes[new URL(route.request().url()).pathname];
    if (body === undefined) {
      return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
}

export async function stubSessions(page: Page, existing: string[], createdId: string | null): Promise<void> {
  await page.route("**/api/sessions", (route) => {
    if (route.request().method() === "POST") {
      if (createdId === null) {
        return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ id: createdId, channel: "webchat" }),
      });
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        existing.map((id) => ({ id, channel: "webchat", user_id: "web_user", agent_id: "assistant", updated_at: new Date().toISOString() })),
      ),
    });
  });
}
