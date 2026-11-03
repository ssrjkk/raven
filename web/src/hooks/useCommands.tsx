import { Code, Database,FileText, Settings, Sparkles } from "lucide-react";
import { useEffect,useState } from "react";
import { useNavigate } from "react-router-dom";

import { getToken } from "../api/client";
import { COMMAND_KEYWORDS } from "./command-keywords";

export interface CommandItem {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  category: "action" | "navigation" | "ai";
  action: () => void;
  shortcut?: string;
  keywords?: string[];
}

function keywordsFor(id: string, provided?: unknown): string[] {
  if (Array.isArray(provided)) return provided.map(String);
  return COMMAND_KEYWORDS[id] ?? [];
}

function parseCategory(raw: unknown): CommandItem["category"] {
  if (raw === "action" || raw === "navigation" || raw === "ai") return raw;
  return "ai";
}

export function useCommands(onToggleTheme?: () => void) {
  const navigate = useNavigate();
  const [commands, setCommands] = useState<CommandItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();

    const fetchCommands = async () => {
      setIsLoading(true);
      try {
        const headers: Record<string, string> = {};
        const token = getToken();
        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }
        const response = await fetch("/api/v1/commands/contextual", {
          signal: ac.signal,
          headers,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const dynamicCommands: unknown = await response.json();
        if (cancelled) return;

        const baseCommands: CommandItem[] = [
          {
            id: "new-project",
            label: "Create a new project",
            description: "Open the AI-guided project wizard",
            icon: <Sparkles className="w-5 h-5 text-accent" />,
            category: "ai",
            action: () => navigate("/scaffold"),
            shortcut: "⌘N",
            keywords: keywordsFor("new-project"),
          },
          {
            id: "toggle-theme",
            label: "Toggle theme",
            description: "Light / Dark / Midnight",
            icon: <Settings className="w-5 h-5 text-secondary" />,
            category: "action",
            action: onToggleTheme ?? (() => {}),
            shortcut: "⌘T",
            keywords: keywordsFor("toggle-theme"),
          },
          ...(Array.isArray(dynamicCommands)
            ? dynamicCommands
                // A command the server gives no screen for cannot be run, so it is not
                // listed at all rather than listed and inert.
                .filter((cmd): cmd is Record<string, unknown> =>
                  typeof cmd === "object" && cmd !== null && typeof (cmd as Record<string, unknown>).route === "string")
                .map((cmd) => ({
                  id: String(cmd.id ?? ""),
                  label: String(cmd.label ?? ""),
                  description: String(cmd.description ?? ""),
                  icon: cmd.icon === "code" ? <Code className="w-5 h-5 text-success" /> :
                        cmd.icon === "db" ? <Database className="w-5 h-5 text-info" /> :
                        <FileText className="w-5 h-5 text-secondary" />,
                  category: parseCategory(cmd.category),
                  action: () => navigate(String(cmd.route)),
                  shortcut: cmd.shortcut ? String(cmd.shortcut) : undefined,
                  keywords: keywordsFor(String(cmd.id ?? ""), cmd.keywords),
                }))
            : []),
        ];
        setCommands(baseCommands);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        console.error("Failed to load commands", err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    fetchCommands();
    return () => { cancelled = true; ac.abort(); };
  }, [navigate, onToggleTheme]);

  return { commands, isLoading };
}
