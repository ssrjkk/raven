import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import Dashboard from "./Dashboard";

vi.mock("../api/client", () => ({
  api: {
    status: vi.fn().mockResolvedValue({
      status: "running",
      channels: ["telegram", "webchat"],
      plugins: 3,
      agents: [{ id: "a1", system_prompt: "helpful", model: "ollama/llama3" }],
      model: "ollama/llama3",
    }),
    health: vi.fn().mockResolvedValue({
      overall: true,
      checks: [
        { name: "nats", ok: true, latency_ms: 5, critical: true },
        { name: "db", ok: true, latency_ms: 2, critical: true },
      ],
    }),
    metrics: vi.fn().mockResolvedValue({
      requests_total: 150,
      errors_total: 3,
      avg_latency_ms: 42,
    }),
    systemStatus: vi.fn().mockResolvedValue({
      channels: 2,
      agents: 1,
      running: true,
      version: "0.4.0",
    }),
  },
  isAuthenticated: vi.fn().mockReturnValue(true),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function renderDashboard() {
  return render(
    <BrowserRouter>
      <Dashboard />
    </BrowserRouter>
  );
}

describe("Dashboard Page", () => {
  it("renders loading state initially", () => {
    renderDashboard();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
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

  it("renders channel names", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText("telegram")).toBeInTheDocument();
    });
    expect(screen.getByText("webchat")).toBeInTheDocument();
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
    expect(screen.getByText("nats")).toBeInTheDocument();
    expect(screen.getByText("db")).toBeInTheDocument();
  });

  it("displays key metrics", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText("Key Metrics")).toBeInTheDocument();
    });
  });
});
