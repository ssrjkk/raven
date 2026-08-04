import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentStream, AgentEvent } from "./AgentStream";

describe("AgentStream", () => {
  it("shows empty state when no events", () => {
    render(<AgentStream events={[]} />);
    expect(screen.getByText(/Агент пока бездействует/)).toBeInTheDocument();
  });

  it("renders flow header", () => {
    const events: AgentEvent[] = [
      { type: "agent_status", event: "agent_started", profile: "coder" },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("Flow State")).toBeInTheDocument();
  });

  it("renders event label and profile badge", () => {
    const events: AgentEvent[] = [
      { type: "agent_status", event: "agent_started", profile: "coder", detail: "coder started" },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("Агент запущен")).toBeInTheDocument();
    expect(screen.getByText("Исполнитель")).toBeInTheDocument();
  });

  it("renders plan steps from data", () => {
    const events: AgentEvent[] = [
      { type: "agent_status", event: "plan_created", profile: "planner", data: { steps: ["Explore", "Implement"] } },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("Explore")).toBeInTheDocument();
    expect(screen.getByText("Implement")).toBeInTheDocument();
  });

  it("renders tool call arguments", () => {
    const events: AgentEvent[] = [
      {
        type: "agent_status",
        event: "tool_call",
        profile: "coder",
        detail: "write_file",
        data: { args: { path: "src/a.ts" } },
      },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("write_file")).toBeInTheDocument();
    expect(screen.getByText(/"path"/)).toBeInTheDocument();
  });

  it("marks completion", () => {
    const events: AgentEvent[] = [
      { type: "agent_status", event: "agent_completed", profile: "coder", detail: "all done" },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("Задача завершена")).toBeInTheDocument();
  });

  it("shows running indicator while not finished", () => {
    const events: AgentEvent[] = [
      { type: "agent_status", event: "agent_started", profile: "coder" },
    ];
    render(<AgentStream events={events} />);
    expect(screen.getByText("Агенты работают...")).toBeInTheDocument();
  });
});
