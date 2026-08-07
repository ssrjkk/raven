import { AnimatePresence,motion } from "framer-motion";
import { Search, Sparkles } from "lucide-react";
import { useEffect, useMemo,useRef, useState } from "react";

import { useTheme } from "../design/ThemeContext";
import { CommandItem, useCommands } from "../hooks/useCommands";
import { FuzzyResult, fuzzyMatch } from "../lib/fuzzy";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export const CommandPalette = ({ isOpen, onClose }: Props) => {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const { toggleTheme } = useTheme();
  const { commands, isLoading } = useCommands(toggleTheme);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredCommands = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return commands.map((cmd) => ({ cmd, indices: [] as number[] }));
    return commands
      .map((cmd) => ({ cmd, match: fuzzyMatch(q, cmd.label) }))
      .filter((entry): entry is { cmd: CommandItem; match: FuzzyResult } => entry.match !== null)
      .sort((a, b) => b.match.score - a.match.score)
      .map(({ cmd, match }) => ({ cmd, indices: match.indices }));
  }, [commands, query]);

  const highlight = (text: string, indices: number[]) => {
    const marks = new Set(indices);
    return (
      <>
        {Array.from(text).map((ch, i) =>
          marks.has(i) ? (
            <mark key={i} className="bg-accent-muted text-accent rounded-sm px-0.5">{ch}</mark>
          ) : (
            <span key={i}>{ch}</span>
          )
        )}
      </>
    );
  };

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setSelectedIndex(0);
    const raf = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(raf);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return;
      if (filteredCommands.length === 0) {
        if (e.key === "Escape") onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredCommands.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % filteredCommands.length);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const entry = filteredCommands[selectedIndex];
        if (entry) { entry.cmd.action(); onClose(); }
      } else if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, filteredCommands, selectedIndex, onClose]);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl z-50"
          >
            <div className="bg-secondary border border-default rounded-xl shadow-[var(--dt-shadow-xl)] overflow-hidden ring-1 ring-white/10">
              <div className="flex items-center px-4 py-3 border-b border-default">
                <Search className="w-5 h-5 text-tertiary mr-3" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Введите команду или опишите действие..."
                  className="flex-1 bg-transparent text-primary placeholder:text-[var(--dt-colors-text-tertiary)] outline-none text-lg"
                />
                {isLoading && (
                  <div className="w-4 h-4 border-2 border-[var(--dt-colors-border-default)] border-t-[var(--dt-colors-accent-default)] rounded-full animate-spin" />
                )}
              </div>

              <div className="max-h-[60vh] overflow-y-auto p-2 space-y-1">
                {filteredCommands.length === 0 ? (
                  <div className="px-4 py-8 text-center text-tertiary">
                    Ничего не найдено. Попробуйте описать задачу иначе.
                  </div>
                ) : (
                  filteredCommands.map(({ cmd, indices }, index) => (
                    <motion.button
                      key={cmd.id}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.03 }}
                      onClick={() => { cmd.action(); onClose(); }}
                      className={`w-full flex items-center px-3 py-3 rounded-lg text-left transition-colors ${
                        index === selectedIndex
                          ? "bg-accent-muted text-primary ring-1 ring-[var(--dt-colors-accent-muted)]"
                          : "text-secondary hover:bg-[var(--dt-colors-bg-hover)]"
                      }`}
                    >
                      <div className={`p-2 rounded-md mr-3 ${index === selectedIndex ? "bg-[var(--dt-colors-accent-muted)]" : "bg-tertiary"}`}>
                        {cmd.icon}
                      </div>
                      <div className="flex-1">
                        <div className="font-medium">{highlight(cmd.label, indices)}</div>
                        <div className="text-sm text-tertiary">{cmd.description}</div>
                      </div>
                      {cmd.shortcut && (
                        <kbd className="kbd">{cmd.shortcut}</kbd>
                      )}
                    </motion.button>
                  ))
                )}
              </div>

              <div className="px-4 py-2 bg-primary border-t border-default flex items-center justify-between text-xs text-tertiary">
                <div className="flex gap-4">
                  <span><kbd className="bg-tertiary px-1.5 py-0.5 rounded">↑↓</kbd> навигация</span>
                  <span><kbd className="bg-tertiary px-1.5 py-0.5 rounded">↵</kbd> выбор</span>
                  <span><kbd className="bg-tertiary px-1.5 py-0.5 rounded">esc</kbd> закрыть</span>
                </div>
                <div className="flex items-center gap-1">
                  <Sparkles className="w-3 h-3 text-accent" />
                  <span>AI-контекст активен</span>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
