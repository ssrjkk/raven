import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeProvider, useTheme } from "./ThemeContext";

function Probe() {
  const { theme, toggleTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button type="button" onClick={toggleTheme}>toggle</button>
      <button type="button" onClick={() => setTheme("midnight")}>midnight</button>
    </div>
  );
}

function renderProbe() {
  return render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>
  );
}

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to dark", () => {
    renderProbe();
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("cycles dark -> light -> midnight -> dark", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme").textContent).toBe("light");
    await user.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme").textContent).toBe("midnight");
    await user.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme").textContent).toBe("dark");
  });

  it("persists selected theme to localStorage", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByText("midnight"));
    expect(localStorage.getItem("raven-theme")).toBe("midnight");
    expect(screen.getByTestId("theme").textContent).toBe("midnight");
    expect(document.documentElement.getAttribute("data-theme")).toBe("midnight");
  });

  it("restores stored theme on mount", () => {
    localStorage.setItem("raven-theme", "midnight");
    renderProbe();
    expect(screen.getByTestId("theme").textContent).toBe("midnight");
  });
});
