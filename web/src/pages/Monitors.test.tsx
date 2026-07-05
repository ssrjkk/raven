import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import Monitors from "./Monitors";

const mockMonitorsData = [
  { id: "m1", name: "Production API", type: "http", target: "https://api.example.com/health", interval_seconds: 60, status: "active", last_check: { status: "up", checked_at: 1700000000 } },
  { id: "m2", name: "Staging DB", type: "tcp", target: "staging-db:5432", interval_seconds: 120, status: "paused", last_check: null },
];

vi.mock("../api/client", () => ({
  api: {
    monitors: vi.fn(),
    monitorToggle: vi.fn().mockResolvedValue({ ok: true }),
  },
  isAuthenticated: vi.fn().mockReturnValue(true),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function renderMonitors() {
  return render(
    <BrowserRouter>
      <Monitors />
    </BrowserRouter>
  );
}

describe("Monitors Page", () => {
  beforeEach(async () => {
    const client = await import("../api/client");
    client.api.monitors = vi.fn().mockResolvedValue(mockMonitorsData);
  });

  it("renders loading state initially", () => {
    renderMonitors();
    expect(screen.getByText("Monitors")).toBeInTheDocument();
  });

  it("renders monitor list after loading", async () => {
    renderMonitors();
    await waitFor(() => {
      expect(screen.getByText("Production API")).toBeInTheDocument();
    });
    expect(screen.getByText("Staging DB")).toBeInTheDocument();
  });

  it("shows empty state when no monitors", async () => {
    const client = await import("../api/client");
    client.api.monitors = vi.fn().mockResolvedValue([]);
    renderMonitors();
    await waitFor(() => {
      expect(screen.getByText("No monitors configured.")).toBeInTheDocument();
    });
  });

  it("renders pause/resume buttons based on status", async () => {
    renderMonitors();
    await waitFor(() => {
      expect(screen.getByText("Pause")).toBeInTheDocument();
      expect(screen.getByText("Resume")).toBeInTheDocument();
    });
  });

  it("handles toggle action", async () => {
    renderMonitors();
    await waitFor(() => {
      expect(screen.getByText("Pause")).toBeInTheDocument();
    });
    const pauseBtn = screen.getByText("Pause");
    await userEvent.click(pauseBtn);
  });
});
