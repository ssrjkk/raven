declare namespace RavenCode {
  interface AgentConfig {
    default: string;
    agents: Record<string, {
      description: string;
      mode: "full" | "plan";
    }>;
  }

  interface CommandConfig {
    name: string;
    description: string;
    handler: string;
    args?: Record<string, unknown>;
  }

  interface ToolConfig {
    name: string;
    description: string;
    schema: unknown;
    handler: string;
  }

  interface TUIConfig {
    theme: {
      name: string;
      colors: Record<string, string>;
      fonts: Record<string, string>;
    };
    layout: Record<string, unknown>;
    editor: Record<string, unknown>;
  }
}
