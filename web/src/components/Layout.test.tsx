import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Layout from "./Layout";

vi.mock("../design/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

vi.mock("../api/client", () => ({
  clearToken: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, Outlet: () => <div data-testid="outlet">content</div> };
});

function renderLayout(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Layout />
    </MemoryRouter>
  );
}

describe("Layout", () => {
  it("renders sidebar with brand", () => {
    renderLayout();
    expect(screen.getByText("Raven AI")).toBeInTheDocument();
  });

  it("renders all navigation items", () => {
    renderLayout();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    expect(screen.getByText("Monitors")).toBeInTheDocument();
    expect(screen.getByText("Routines")).toBeInTheDocument();
    expect(screen.getByText("Code")).toBeInTheDocument();
    expect(screen.getByText("IDE")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("renders theme toggle and sign out", () => {
    renderLayout();
    expect(screen.getByText("☀️ Light")).toBeInTheDocument();
    expect(screen.getByText("Sign Out")).toBeInTheDocument();
  });

  it("renders version badge", () => {
    renderLayout();
    expect(screen.getByText(/Raven AI v/)).toBeInTheDocument();
  });

  it("renders outlet content", () => {
    renderLayout();
    expect(screen.getByTestId("outlet")).toBeInTheDocument();
  });
});
