import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import Login from "./Login";

// Mock api client
vi.mock("../api/client", () => ({
  api: {
    login: vi.fn().mockResolvedValue({ token: "test-token", user: { id: "1", role: "user" } }),
    register: vi.fn().mockResolvedValue({ token: "test-token", user: { id: "1", role: "user" } }),
  },
  setToken: vi.fn(),
  isAuthenticated: vi.fn().mockReturnValue(false),
}));

function renderLogin() {
  return render(
    <BrowserRouter>
      <Login />
    </BrowserRouter>
  );
}

describe("Login Page", () => {
  it("renders sign-in form by default", () => {
    renderLogin();
    expect(screen.getByText("Sign in to your account")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows username and password fields", () => {
    renderLogin();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("switches to register mode", async () => {
    renderLogin();
    const toggle = screen.getByText(/register/i);
    await userEvent.click(toggle);
    expect(screen.getByText("Create an account")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /register/i })).toBeInTheDocument();
  });

  it("disables submit while loading", async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText(/username/i), "testuser");
    await userEvent.type(screen.getByLabelText(/password/i), "password123!");
    const button = screen.getByRole("button", { name: /sign in/i });
    await userEvent.click(button);
    expect(button).toBeDisabled();
  });

  it("renders Raven AI heading", () => {
    renderLogin();
    expect(screen.getByText("Raven AI")).toBeInTheDocument();
  });
});
