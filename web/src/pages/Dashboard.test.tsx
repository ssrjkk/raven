import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { metrics, status, systemStatus } from "../../e2e/fixtures/api";
import { healthDegraded } from "../../e2e/fixtures/health";
import { renderWithProviders } from "../test/test-utils";
import Dashboard from "./Dashboard";

// The payloads are the answers of the routes themselves (scripts/gen_api_fixtures.py). They used to be typed
// here by hand, and the hand-written ones were fictions the page could not fail on: metric keys
// `requests_total`/`avg_latency_ms` that `metrics.snapshot()` has never emitted, a `version` of its own, and a
// channel list that disagreed with what `/api/admin/system/status` counted one line below it.
vi.mock("../api/client", () => ({
  api: {
    status: vi.fn().mockResolvedValue(status),
    health: vi.fn().mockResolvedValue(healthDegraded),
    metrics: vi.fn().mockResolvedValue(metrics),
    systemStatus: vi.fn().mockResolvedValue(systemStatus),
  },
  isAuthenticated: vi.fn().mockReturnValue(true),
  getToken: vi.fn().mockReturnValue(null),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function renderDashboard() {
  return renderWithProviders(<Dashboard />);
}

describe("Dashboard Page", () => {
  it("renders loading state initially", async () => {
    renderDashboard();
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
  });

  it("renders metric cards after loading", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getAllByText("Channels").length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("Plugins")).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
  });

  it("renders the channels the gateway reports", async () => {
    renderDashboard();
    for (const channel of status.channels) {
      expect(await screen.findByText(channel)).toBeInTheDocument();
    }
  });

  it("shows running status indicator", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText("Running")).toBeInTheDocument();
    });
  });

  it("renders health checks section", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText("Health Checks")).toBeInTheDocument();
    });
    // The payload is the route's own answer (scripts/gen_health_fixture.py), so these are the checks
    // production registers and the `detail` the registry puts on a passing probe versus a failed one.
    expect(screen.getByText("database")).toBeInTheDocument();
    expect(screen.getByText("llm")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("no route to host")).toBeInTheDocument();
  });

  it("displays key metrics", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText("Key Metrics")).toBeInTheDocument();
    });
  });
});
