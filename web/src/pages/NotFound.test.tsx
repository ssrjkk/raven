import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import NotFound from "./NotFound";

function renderNotFound() {
  return render(
    <BrowserRouter>
      <NotFound />
    </BrowserRouter>
  );
}

describe("NotFound Page", () => {
  it("renders 404 heading", () => {
    renderNotFound();
    expect(screen.getByText("404")).toBeInTheDocument();
  });

  it("renders page not found message", () => {
    renderNotFound();
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });

  it("renders back to dashboard link", () => {
    renderNotFound();
    const link = screen.getByText("Back to Dashboard");
    expect(link).toBeInTheDocument();
    expect(link.closest("a")).toHaveAttribute("href", "/");
  });
});
