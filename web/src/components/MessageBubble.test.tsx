import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MessageBubble from "./MessageBubble";

describe("MessageBubble", () => {
  const baseMessage = {
    id: "1",
    content: "Hello world",
    created_at: "2025-01-01T00:00:00Z",
  };

  it("renders user message with right alignment", () => {
    render(<MessageBubble message={{ ...baseMessage, role: "user" }} />);
    const bubble = screen.getByText("Hello world");
    expect(bubble).toBeInTheDocument();
  });

  it("renders assistant message with left alignment", () => {
    render(<MessageBubble message={{ ...baseMessage, role: "assistant" }} />);
    const bubble = screen.getByText("Hello world");
    expect(bubble).toBeInTheDocument();
  });

  it("renders system message", () => {
    render(<MessageBubble message={{ ...baseMessage, role: "system" }} />);
    const bubble = screen.getByText("Hello world");
    expect(bubble).toBeInTheDocument();
  });

  it("renders tool message", () => {
    render(<MessageBubble message={{ ...baseMessage, role: "tool" }} />);
    const bubble = screen.getByText("Hello world");
    expect(bubble).toBeInTheDocument();
  });

  it("renders code content with pre tag", () => {
    const code = "```const x = 1;```";
    render(<MessageBubble message={{ ...baseMessage, content: code, role: "assistant" }} />);
    expect(screen.getByText("const x = 1;")).toBeInTheDocument();
  });

  it("renders timestamps", () => {
    render(<MessageBubble message={{ ...baseMessage, role: "user" }} />);
    expect(screen.getByText(/2025/)).toBeInTheDocument();
  });

  it("handles empty content", () => {
    render(<MessageBubble message={{ ...baseMessage, content: "", role: "assistant" }} />);
    expect(screen.getByText("")).toBeInTheDocument();
  });

  it("handles long messages without crashing", () => {
    const long = "A".repeat(10000);
    render(<MessageBubble message={{ ...baseMessage, content: long, role: "user" }} />);
    expect(screen.getByText(long)).toBeInTheDocument();
  });
});
