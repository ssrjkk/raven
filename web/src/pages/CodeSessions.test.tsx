import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import CodeSessions from "./CodeSessions";

vi.mock("../api/client", () => ({
  api: {
    codeSessions: vi.fn(),
  },
  isAuthenticated: vi.fn().mockReturnValue(true),
}));

vi.mock("../components/Toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockSessions = [
  { id: "s1", goal: "Fix login bug", status: "active", project_path: "/app/src", files: 12 },
  { id: "s2", goal: "Add dark mode", status: "completed", project_path: "/app/src", files: 5 },
];

function renderCodeSessions() {
  return render(
    <BrowserRouter>
      <CodeSessions />
    </BrowserRouter>
  );
}

describe("CodeSessions Page", () => {
  beforeEach(async () => {
    const client = await import("../api/client");
    client.api.codeSessions = vi.fn().mockResolvedValue(mockSessions);
  });

  it("renders loading state initially", () => {
    renderCodeSessions();
    expect(screen.getByText("Code Sessions")).toBeInTheDocument();
  });

  it("renders sessions after loading", async () => {
    renderCodeSessions();
    await waitFor(() => {
      expect(screen.getByText("Fix login bug")).toBeInTheDocument();
    });
    expect(screen.getByText("Add dark mode")).toBeInTheDocument();
  });

  it("shows empty state when no sessions", async () => {
    const client = await import("../api/client");
    client.api.codeSessions = vi.fn().mockResolvedValue([]);
    renderCodeSessions();
    await waitFor(() => {
      expect(screen.getByText("No coding sessions.")).toBeInTheDocument();
    });
  });
});
