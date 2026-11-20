import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DiffViewer from "./DiffViewer";

const DIFF = [
  "--- a/app.py",
  "+++ b/app.py",
  "@@ -1,2 +1,2 @@",
  " ctx & entities",
  "-old <div>",
  '+new "quoted"',
].join("\n");

describe("DiffViewer", () => {
  it("prints the code a diff carries, not the markup it escapes", () => {
    render(<DiffViewer diff={DIFF} singlePane />);
    expect(screen.getByText(/old/).textContent).toBe("-old <div>");
    expect(screen.getByText(/ctx/).textContent).toContain(" ctx & entities");
  });

  it("marks each row with the sheet's own diff classes", () => {
    render(<DiffViewer diff={DIFF} singlePane />);
    const row = screen.getByText(/new/).closest("td");
    expect(row?.className).toContain("diff-add");
    expect(row?.querySelector("span")?.className).toContain("text-success");
    expect(row?.hasAttribute("style")).toBe(false);
  });
});
