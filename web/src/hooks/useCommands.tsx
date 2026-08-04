import { Code, Database,FileText, Settings, Sparkles } from "lucide-react";
import { useEffect,useState } from "react";
import { useNavigate } from "react-router-dom";

import { getToken } from "../api/client";

export interface CommandItem {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  category: "action" | "navigation" | "ai";
  action: () => void;
  shortcut?: string;
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
            label: "Создать новый проект",
            description: "Запустить мастер создания проекта с AI",
            icon: <Sparkles className="w-5 h-5 text-indigo-400" />,
            category: "ai",
            action: () => navigate("/scaffold"),
            shortcut: "⌘N",
          },
          {
            id: "toggle-theme",
            label: "Переключить тему",
            description: "Светлая / Темная / Системная",
            icon: <Settings className="w-5 h-5 text-zinc-400" />,
            category: "action",
            action: onToggleTheme ?? (() => {}),
            shortcut: "⌘T",
          },
          ...(Array.isArray(dynamicCommands) ? dynamicCommands.map((cmd: Record<string, unknown>) => ({
            id: String(cmd.id ?? ""),
            label: String(cmd.label ?? ""),
            description: String(cmd.description ?? ""),
            icon: cmd.icon === "code" ? <Code className="w-5 h-5 text-emerald-400" /> :
                  cmd.icon === "db" ? <Database className="w-5 h-5 text-blue-400" /> :
                  <FileText className="w-5 h-5 text-zinc-400" />,
            category: parseCategory(cmd.category),
            action: () => {},
            shortcut: cmd.shortcut ? String(cmd.shortcut) : undefined,
          })) : []),
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
