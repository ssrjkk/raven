import { defineConfig, devices } from "@playwright/test";

// The specs run against `vite preview` over the built bundle, not the dev server: what the image
// ships is what is tested, so a build that produces a broken SPA fails here instead of in production.
const PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["html", { outputFolder: "playwright-report" }],
    ["json", { outputFile: "playwright-results/results.json" }],
    ["junit", { outputFile: "playwright-results/junit.xml" }],
  ],
  use: {
    // `localhost`, not `127.0.0.1`: vite binds the preview server to the loopback address its host
    // name resolves to, and on this machine that is `::1` — the readiness probe against the IPv4
    // literal times out and the whole run dies before the first spec.
    baseURL: process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${PORT}`,
    // The built bundle registers `/sw.js` (src/main.tsx), and requests a service worker issues are not
    // interceptable by `page.route` — measured: with the worker running, 0 of 5 `/api/*` calls reached a
    // route handler, so every stub silently fell through to the offline page and the specs asserted
    // against a state no developer sees. Blocking the worker keeps the specs on the app's own fetches.
    serviceWorkers: "block",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "ignore",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
});
