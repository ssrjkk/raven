import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { ACCENT_PRESETS } from "../design/accent";
import { applyThemeScheme } from "../design/scheme";
import { useTheme } from "../design/ThemeContext";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Settings() {
  const [customHex, setCustomHex] = useState("");
  const [schemePrompt, setSchemePrompt] = useState("");
  const { toast } = useToast();
  const { accentColor, setAccentColor, theme, toggleTheme, resetScheme } = useTheme();

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
        <div
          className="rounded-xl p-4 space-y-3"
          style={{
            backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))",
            border: "1px solid var(--dt-colors-border-default)",
          }}
        >
          <Skeleton width={96} height={16} />
          {[1, 2, 3].map((i) => <Skeleton key={i} height={32} rounded="md" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* Theme */}
      <div className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card)", border: "1px solid var(--dt-colors-border-default)" }}>
        <h2 className="text-sm font-semibold mb-3 text-primary">Theme</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm text-secondary">Appearance</span>
          <button
            onClick={toggleTheme}
            className="px-4 py-1.5 rounded-lg text-sm font-medium transition"
            style={{
              backgroundColor: "var(--dt-colors-accent-muted)",
              color: "var(--dt-colors-accent-default)",
            }}
          >
            {theme === "dark" ? "Switch to Light" : "Switch to Dark"}
          </button>
        </div>
      </div>

      {/* Accent Color */}
      <div className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card)", border: "1px solid var(--dt-colors-border-default)" }}>
        <h2 className="text-sm font-semibold mb-3 text-primary">Accent Color</h2>
        <div className="flex flex-wrap gap-3 mb-4">
          {ACCENT_PRESETS.map((p) => (
            <button
              key={p.hex}
              onClick={() => handleAccentChange(p.hex)}
              className="w-8 h-8 rounded-full transition-transform hover:scale-110 active:scale-95"
              style={{
                backgroundColor: p.hex,
                boxShadow: accentColor === p.hex ? `0 0 0 2px var(--dt-colors-bg-primary), 0 0 0 4px ${p.hex}` : "none",
              }}
              title={p.name}
            />
          ))}
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
            className="flex-1 bg-transparent border rounded-lg px-3 py-1.5 text-sm font-mono outline-none"
            style={{
              color: "var(--dt-colors-text-primary)",
              borderColor: "var(--dt-colors-border-default)",
            }}
          />
          <button
            onClick={() => {
              if (/^#[0-9a-f]{6}$/i.test(customHex)) handleAccentChange(customHex);
            }}
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-40"
            style={{
              backgroundColor: "var(--dt-colors-accent-muted)",
              color: "var(--dt-colors-accent-default)",
            }}
            disabled={!/^#[0-9a-f]{6}$/i.test(customHex)}
          >
            Apply
          </button>
        </div>
      </div>

      {/* AI Color Scheme */}
      <div className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card)", border: "1px solid var(--dt-colors-border-default)" }}>
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
            className="flex-1 bg-transparent border rounded-lg px-3 py-1.5 text-sm outline-none"
            style={{
              color: "var(--dt-colors-text-primary)",
              borderColor: "var(--dt-colors-border-default)",
            }}
          />
          <button
            onClick={() => {
              if (schemePrompt.trim()) generateScheme.mutate(schemePrompt.trim());
            }}
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition disabled:opacity-40"
            style={{
              backgroundColor: "var(--dt-colors-accent-muted)",
              color: "var(--dt-colors-accent-default)",
            }}
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
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition"
            style={{
              backgroundColor: "var(--dt-colors-surface-elevated)",
              color: "var(--dt-colors-text-secondary)",
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Config */}
      <div className="rounded-xl p-4" style={{ backgroundColor: "var(--dt-colors-surface-card)", border: "1px solid var(--dt-colors-border-default)" }}>
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
        className="bg-red-700 hover:bg-red-600 disabled:bg-red-900/50 text-white px-5 py-2 rounded-xl text-sm font-medium transition">
        {shutdown.isPending ? "Shutting down..." : "Shutdown Raven"}
      </button>
    </div>
  );
}