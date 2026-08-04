import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectInsights from "./ProjectInsights";
import { renderWithProviders } from "../test/test-utils";

vi.mock("../api/client", () => ({
  api: {
    projectInsights: vi.fn().mockResolvedValue({
      project_id: "default",
      time_saved_minutes: 90,
      ai_contribution_percent: 62.5,
      success_rate: 100,
      token_cost_estimate: 0.0123,
      files: 12,
      code_lines: 340,
      commits: 9,
      active_days: 3,
      trend: [
        { date: "2026-07-30", commits: 2 },
        { date: "2026-07-31", commits: 4 },
        { date: "2026-08-01", commits: 3 },
      ],
      generated_at: "2026-08-01T10:00:00Z",
    }),
  },
}));

describe("ProjectInsights", () => {
  it("renders stat cards with formatted values", async () => {
    renderWithProviders(<ProjectInsights />);
    await waitFor(() => {
      expect(screen.getByText("1 ч 30 мин")).toBeInTheDocument();
    });
    expect(screen.getByText("62.5%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("$0.0123")).toBeInTheDocument();
  });

  it("renders summary stats", async () => {
    renderWithProviders(<ProjectInsights />);
    await waitFor(() => {
      expect(screen.getByText("9")).toBeInTheDocument();
    });
    expect(screen.getByText("340")).toBeInTheDocument();
  });

  it("renders chart section", async () => {
    renderWithProviders(<ProjectInsights />);
    await waitFor(() => {
      expect(screen.getByText("Коммиты по дням")).toBeInTheDocument();
    });
  });

  it("renders generated_at timestamp", async () => {
    renderWithProviders(<ProjectInsights />);
    await waitFor(() => {
      expect(screen.getByText(/Обновлено:/)).toBeInTheDocument();
    });
  });
});
