import { screen } from "@testing-library/react";
import { describe, expect,it } from "vitest";

import NotFound from "./NotFound";
import { renderWithProviders } from "../test/test-utils";

function renderNotFound() {
  return renderWithProviders(<NotFound />);
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
