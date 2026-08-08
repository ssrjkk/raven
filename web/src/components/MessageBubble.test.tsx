import { render, screen } from "@testing-library/react";
import { describe, expect,it } from "vitest";

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
    const { container } = render(<MessageBubble message={{ ...baseMessage, content: "", role: "assistant" }} />);
    expect(container.querySelector(".prose")).toBeInTheDocument();
  });

  it("handles long messages without crashing", () => {
    const long = "A".repeat(10000);
    render(<MessageBubble message={{ ...baseMessage, content: long, role: "user" }} />);
    expect(screen.getByText(long)).toBeInTheDocument();
  });

  it("renders artifact JSON as an artifact card", () => {
    const artifact = JSON.stringify({
      artifact_id: "abc12345",
      title: "Login Form",
      type: "react",
      content: "export const Login = () => <h1>Hi</h1>",
      status: "created",
    });
    render(<MessageBubble message={{ ...baseMessage, content: artifact, role: "assistant" }} />);
    expect(screen.getByText("Login Form")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
    expect(screen.getByText(/export const Login/)).toBeInTheDocument();
  });

  it("does not render artifact card for user messages", () => {
    const artifact = JSON.stringify({
      artifact_id: "abc12345",
      title: "Login Form",
      type: "react",
      content: "export const Login = () => 1",
      status: "created",
    });
    render(<MessageBubble message={{ ...baseMessage, content: artifact, role: "user" }} />);
    expect(screen.queryByText("Login Form")).not.toBeInTheDocument();
  });
});
