import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach,describe, expect, it, vi } from "vitest";

import Settings from "./Settings";
import { renderWithProviders } from "../test/test-utils";

vi.mock("../api/client", () => ({
  api: {
    config: vi.fn(),
    shutdown: vi.fn().mockResolvedValue({ ok: true }),
    getTheme: vi.fn().mockResolvedValue({ accentColor: "#7c3aed" }),
    saveTheme: vi.fn().mockResolvedValue({ ok: true }),
    generateTheme: vi.fn().mockResolvedValue({
      name: "AI · neon cyberpunk",
      description: "neon cyberpunk",
      accent: "#22d3ee",
      palette: {
        accent: { default: "#22d3ee", hover: "#67e8f9" },
        bg: { primary: "#08111f" },
      },
    }),
  },
  isAuthenticated: vi.fn().mockReturnValue(true),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function renderSettings() {
  return renderWithProviders(<Settings />);
}

describe("Settings Page", () => {
  beforeEach(async () => {
    const client = await import("../api/client");
    client.api.config = vi.fn().mockResolvedValue({
      db_path: "/data/raven.db",
      log_level: "INFO",
      max_tokens: 4096,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("renders heading", async () => {
    renderSettings();
    expect(await screen.findByText("Settings")).toBeInTheDocument();
  });

  it("renders config after loading", async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText("Configuration")).toBeInTheDocument();
    });
    expect(screen.getByText("db_path")).toBeInTheDocument();
    expect(screen.getByText("/data/raven.db")).toBeInTheDocument();
    expect(screen.getByText("log_level")).toBeInTheDocument();
    expect(screen.getByText("max_tokens")).toBeInTheDocument();
  });

  it("renders shutdown button", async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText("Shutdown Raven")).toBeInTheDocument();
    });
  });

  it("handles shutdown click", async () => {
    const client = await import("../api/client");
    client.api.shutdown = vi.fn().mockImplementation(() => new Promise((r) => setTimeout(() => r({ ok: true }), 100)));
    const user = userEvent.setup();
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText("Shutdown Raven")).toBeInTheDocument();
    });
    const btn = screen.getByText("Shutdown Raven");
    await user.click(btn);
    await waitFor(() => {
      expect(screen.getByText("Shutting down...")).toBeInTheDocument();
    });
  });

  it("renders AI color scheme section", async () => {
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText("AI Color Scheme")).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("e.g. neon cyberpunk with mint accents")).toBeInTheDocument();
  });

  it("generates and applies a color scheme", async () => {
    const client = await import("../api/client");
    client.api.generateTheme = vi.fn().mockResolvedValue({
      name: "AI · neon cyberpunk",
      description: "neon cyberpunk",
      accent: "#22d3ee",
      palette: {
        accent: { default: "#22d3ee", hover: "#67e8f9" },
        bg: { primary: "#08111f" },
      },
    });
    const user = userEvent.setup();
    renderSettings();
    await waitFor(() => {
      expect(screen.getByText("AI Color Scheme")).toBeInTheDocument();
    });
    await user.type(screen.getByPlaceholderText("e.g. neon cyberpunk with mint accents"), "neon cyberpunk");
    await user.click(screen.getByText("Generate"));
    await waitFor(() => {
      expect(client.api.generateTheme).toHaveBeenCalledWith("neon cyberpunk");
    });
    await waitFor(() => {
      expect(document.documentElement.style.getPropertyValue("--dt-colors-accent-default")).toBe("#22d3ee");
    });
  });
});
