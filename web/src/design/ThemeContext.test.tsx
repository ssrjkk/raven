import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeProvider, useTheme } from "./ThemeContext";
import darkTokens from "./tokens.json";

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

function AccentProbe() {
  const { accentColor, setAccentColor, resetScheme } = useTheme();
  return (
    <div>
      <span data-testid="accent">{accentColor}</span>
      <button type="button" onClick={() => setAccentColor("#f59e0b")}>amber</button>
      <button type="button" onClick={resetScheme}>reset</button>
    </div>
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

  it("returns the accent to the theme's own default hex when the scheme is reset", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <AccentProbe />
      </ThemeProvider>,
    );
    await user.click(screen.getByText("amber"));
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--dt-colors-accent-default")).toMatch(/^#[0-9a-f]{6}$/i);

    // The accent is fed through the palette maths, so a reset that hands it anything but a hex turns every
    // accent colour the shell paints with into NaN -- the buttons stay there and lose their colour.
    await user.click(screen.getByText("reset"));
    expect(screen.getByTestId("accent").textContent).toBe(darkTokens.colors.accent.default);
    expect(localStorage.getItem("raven-accent")).toBe(darkTokens.colors.accent.default);
    expect(root.style.getPropertyValue("--dt-colors-accent-default")).toMatch(/^#[0-9a-f]{6}$/i);
    expect(root.style.getPropertyValue("--dt-colors-text-link")).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
