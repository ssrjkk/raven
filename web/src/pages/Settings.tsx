import { useMutation } from "@tanstack/react-query";
import { Moon, MoonStar, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { ACCENT_PRESETS } from "../design/accent";
import { applyThemeScheme } from "../design/scheme";
import { type Theme, useTheme } from "../design/ThemeContext";
import { useApiQuery } from "../hooks/useApiQuery";

const THEMES: { id: Theme; label: string; icon: typeof Sun }[] = [
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
  { id: "midnight", label: "Midnight", icon: MoonStar },
];

export default function Settings() {
  const [customHex, setCustomHex] = useState("");
  const [schemePrompt, setSchemePrompt] = useState("");
  const { toast } = useToast();
  const { accentColor, setAccentColor, theme, setTheme, resetScheme } = useTheme();

  const generateScheme = useMutation({
    mutationFn: (prompt: string) => api.generateTheme(prompt),
    onSuccess: (scheme) => {
      applyThemeScheme(scheme.palette);
      setAccentColor(scheme.accent);
      toast(scheme.name, "success");
    },
    onError: (err) => {
      if (err instanceof Error) toast(`Theme generation failed: ${err.message}`, "error");
    },
  });

  const { data: configData, isLoading } = useApiQuery<Record<string, string>>(["config"], () => api.config());
  const config = configData ?? {};

  useEffect(() => {
    api.getTheme().then((r) => {
      if (r?.accentColor && r.accentColor !== accentColor) {
        setAccentColor(r.accentColor);
      }
    }).catch(e => console.error("settings:", e));
  }, []);

  function handleAccentChange(hex: string) {
    setAccentColor(hex);
    api.saveTheme(hex).catch(e => console.error("settings:", e));
  }

  const shutdown = useMutation({
    mutationFn: () => {
      if (!window.confirm("Shutdown Raven AI? This will stop the server.")) {
        return Promise.reject(new Error("cancelled"));
      }
      return api.shutdown();
    },
    onSuccess: () => toast("Server shutting down...", "info"),
    onError: (err) => {
      if (err instanceof Error && err.message !== "cancelled") {
        toast("Shutdown failed", "error");
      }
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton width={120} height={28} />
        <div className="card p-4 space-y-3">
          <Skeleton width={96} height={16} />
          {[1, 2, 3].map((i) => <Skeleton key={i} height={32} rounded="md" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Configure Raven, themes, and server behavior" />

      {/* Theme */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold mb-3 text-primary">Theme</h2>
        <div className="grid grid-cols-3 gap-2">
          {THEMES.map(({ id, label, icon: Icon }) => {
            const active = theme === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setTheme(id)}
                aria-pressed={active}
                className="flex flex-col items-center gap-1.5 px-3 py-3 rounded-xl text-sm font-medium transition-transform hover:scale-[1.02] active:scale-95"
                style={
                  active
                    ? {
                        backgroundColor: "var(--dt-colors-accent-muted)",
                        color: "var(--dt-colors-accent-default)",
                        border: "1px solid var(--dt-colors-accent-muted)",
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.06)",
                      }
                    : {
                        backgroundColor: "var(--dt-colors-bg-tertiary)",
                        color: "var(--dt-colors-text-secondary)",
                        border: "1px solid var(--dt-colors-border-default)",
                      }
                }
              >
                <Icon size={18} className="shrink-0" />
                {label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-tertiary mt-3">
          Midnight is an AMOLED-optimized dark theme for deep blacks and richer glow.
        </p>
      </div>

      {/* Accent Color */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold mb-3 text-primary">Accent Color</h2>
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2 mb-4">
          {ACCENT_PRESETS.map((p) => {
            const active = accentColor === p.hex;
            return (
              <button
                key={p.hex}
                type="button"
                onClick={() => handleAccentChange(p.hex)}
                className="flex flex-col items-center gap-1.5 rounded-lg px-1 py-2 transition-colors"
                style={{
                  backgroundColor: active ? "var(--dt-colors-accent-subtle)" : "transparent",
                }}
                title={p.name}
              >
                <span
                  className="w-6 h-6 rounded-full transition-transform hover:scale-110 active:scale-95"
                  style={{
                    backgroundColor: p.hex,
                    boxShadow: active
                      ? `0 0 0 2px var(--dt-colors-bg-primary), 0 0 0 4px ${p.hex}, 0 0 10px ${p.hex}80`
                      : "none",
                  }}
                />
                <span className="text-[10px] leading-none" style={{ color: "var(--dt-colors-text-tertiary)" }}>
                  {p.name}
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-full flex-shrink-0"
            style={{ backgroundColor: accentColor }}
          />
          <input
            type="color"
            value={accentColor}
            onChange={(e) => handleAccentChange(e.target.value)}
            className="w-10 h-8 rounded cursor-pointer border-0 p-0"
            style={{ backgroundColor: "transparent" }}
          />
          <input
            type="text"
            value={customHex}
            onChange={(e) => setCustomHex(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && /^#[0-9a-f]{6}$/i.test(customHex)) {
                handleAccentChange(customHex);
              }
            }}
            placeholder="#7c3aed"
            className="input-base flex-1 font-mono"
          />
          <button
            onClick={() => {
              if (/^#[0-9a-f]{6}$/i.test(customHex)) handleAccentChange(customHex);
            }}
            className="btn-primary"
            disabled={!/^#[0-9a-f]{6}$/i.test(customHex)}
          >
            Apply
          </button>
        </div>
      </div>

      {/* AI Color Scheme */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold mb-1 text-primary">AI Color Scheme</h2>
        <p className="text-xs text-secondary mb-3">
          Describe a mood or palette — the LLM designs a full dark-mode color scheme and applies it live.
        </p>
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={schemePrompt}
            onChange={(e) => setSchemePrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && schemePrompt.trim()) {
                generateScheme.mutate(schemePrompt.trim());
              }
            }}
            placeholder="e.g. neon cyberpunk with mint accents"
            className="input-base flex-1"
          />
          <button
            onClick={() => {
              if (schemePrompt.trim()) generateScheme.mutate(schemePrompt.trim());
            }}
            className="btn-primary"
            disabled={generateScheme.isPending || !schemePrompt.trim()}
          >
            {generateScheme.isPending ? "Generating..." : "Generate"}
          </button>
          <button
            onClick={() => {
              resetScheme();
              setAccentColor("#7c3aed");
              toast("Theme reset to defaults", "info");
            }}
            className="btn-ghost"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Config */}
      <div className="card p-4">
        <h2 className="text-sm font-semibold mb-3 text-primary">Configuration</h2>
        <div className="space-y-2 text-sm">
          {Object.entries(config).map(([k, v]) => (
            <div key={k} className="flex justify-between py-1" style={{ borderBottom: "1px solid var(--dt-colors-border-muted)" }}>
              <span className="text-tertiary">{k}</span>
              <span className="font-mono text-primary">{String(v).slice(0, 40)}</span>
            </div>
          ))}
        </div>
      </div>

      <button onClick={() => shutdown.mutate()} disabled={shutdown.isPending}
        className="px-5 py-2 rounded-xl text-sm font-medium transition bg-danger-subtle text-danger disabled:opacity-50">
        {shutdown.isPending ? "Shutting down..." : "Shutdown Raven"}
      </button>
    </div>
  );
}