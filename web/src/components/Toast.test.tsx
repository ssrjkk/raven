import { act, fireEvent,render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "./Toast";

function TestHarness() {
  const { toast } = useToast();
  return (
    <div>
      <button onClick={() => toast("Hello info")}>Info</button>
      <button onClick={() => toast("Hello success", "success")}>Success</button>
      <button onClick={() => toast("Hello error", "error")}>Error</button>
    </div>
  );
}

function renderToast() {
  return render(
    <ToastProvider>
      <TestHarness />
    </ToastProvider>
  );
}

describe("Toast", () => {
  it("renders children", () => {
    renderToast();
    expect(screen.getByText("Info")).toBeInTheDocument();
  });

  it("shows toast on trigger", () => {
    renderToast();
    fireEvent.click(screen.getByText("Info"));
    expect(screen.getByText("Hello info")).toBeInTheDocument();
  });

  it("removes toast after timeout", () => {
    vi.useFakeTimers();
    renderToast();
    fireEvent.click(screen.getByText("Info"));
    expect(screen.getByText("Hello info")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(4100 + 300); });
    expect(screen.queryByText("Hello info")).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("dismisses toast via close button", () => {
    vi.useFakeTimers();
    renderToast();
    fireEvent.click(screen.getByText("Info"));
    expect(screen.getByText("Hello info")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.queryByText("Hello info")).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});
