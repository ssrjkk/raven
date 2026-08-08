import { Activity, AlertTriangle, BarChart3, Bot, CheckCircle, ChevronDown, ChevronRight, Clock, Code, Database, FileText, GitBranch, GitCommit, GitPullRequest, Globe, Info, Key, Layers, Link, Loader2, Lock, LogOut, Mail, MapPin, Maximize2, Menu, Minimize2, Moon, MoreHorizontal, Move, Pause, Play, Plus, RefreshCw, Save, Search, Settings, Shield, Sliders, Sparkles, Star, StopCircle, Sun, Terminal, Trash2, Upload, User, Users, Video, Volume2, VolumeX, Wifi, X, XCircle, Zap } from "lucide-react";
import { useState } from "react";

import MessageBubble from "../components/MessageBubble";
import { Skeleton, SkeletonCard, SkeletonCircle, SkeletonTableRow, SkeletonText } from "../components/Skeleton";
import TokenUsageBar from "../components/TokenUsageBar";

const iconList = [
  Sparkles, Search, Code, Terminal, Bot, User, AlertTriangle, CheckCircle, Info, XCircle,
  ChevronRight, ChevronDown, Menu, X, Sun, Moon, Settings, GitBranch, GitCommit, GitPullRequest,
  Activity, BarChart3, Clock, Database, FileText, Globe, Key, Layers, Link, Loader2, Lock,
  LogOut, Mail, MapPin, Maximize2, Minimize2, MoreHorizontal, Move, Pause, Play, Plus,
  RefreshCw, Save, Shield, Sliders, Star, StopCircle, Trash2, Upload, Users, Video, Volume2, VolumeX, Wifi, Zap,
];

export default function ComponentLibrary() {
  const [copied, setCopied] = useState("");

  const copyCode = (code: string, label: string) => {
    navigator.clipboard.writeText(code);
    setCopied(label);
    setTimeout(() => setCopied(""), 1500);
  };

  const section = (title: string, desc: string, children: React.ReactNode, code: string) => (
    <div className="rounded-xl p-5 card-bordered">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-xs mt-0.5 text-tertiary">{desc}</p>
        </div>
        <button onClick={() => copyCode(code, title)}
          className="text-[11px] px-2 py-1 rounded shrink-0 transition bg-tertiary text-tertiary">
          {copied === title ? "Copied!" : "Code"}
        </button>
      </div>
      {children}
      {copied === title && (
        <div className="mt-3 p-2 rounded text-xs font-mono whitespace-pre-wrap max-h-48 overflow-auto" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-secondary)", border: "1px solid var(--dt-colors-border-default)" }}>
          {code}
        </div>
      )}
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Layers className="w-6 h-6" style={{ color: "var(--dt-colors-accent-default)" }} />
          Component Library
        </h1>
        <p className="text-sm mt-1 text-tertiary">
          Live preview of all UI components. Click "Code" on any section to copy the source snippet.
        </p>
      </div>

      <div className="space-y-6">
        {/* Typography */}
        {section("Typography", "Text styles used across the app", (
          <div className="space-y-2">
            <h1 className="text-2xl font-bold">Heading 1 (text-2xl font-bold)</h1>
            <h2 className="text-xl font-semibold">Heading 2 (text-xl font-semibold)</h2>
            <h3 className="text-lg font-semibold">Heading 3 (text-lg font-semibold)</h3>
            <p className="text-sm">Body text (text-sm) — the standard paragraph style.</p>
            <p className="text-xs text-tertiary">Caption (text-xs, tertiary colour)</p>
            <p className="text-[11px] font-mono px-1.5 py-0.5 rounded inline-block bg-tertiary">Tag / badge text (11px monospace)</p>
          </div>
        ), `<h1 className="text-2xl font-bold">...</h1>\n<h2 className="text-xl font-semibold">...</h2>\n<p className="text-sm">...</p>\n<p className="text-xs text-tertiary">...</p>`)}

        {/* Buttons */}
        {section("Buttons", "Primary, secondary, ghost, and danger variants", (
          <div className="flex flex-wrap gap-3 items-center">
            <button className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white">Primary</button>
            <button className="px-4 py-2 rounded-lg text-sm font-medium bg-tertiary text-primary border-default">Secondary</button>
            <button className="px-4 py-2 rounded-lg text-sm font-medium text-secondary">Ghost</button>
            <button className="px-4 py-2 rounded-lg text-sm font-medium bg-danger-subtle text-danger">Danger</button>
            <button disabled className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 bg-accent text-white">Disabled</button>
            <button className="px-3 py-2 rounded-lg text-sm font-medium flex items-center gap-1.5 bg-accent text-white">
              <Plus className="w-4 h-4" /> With Icon
            </button>
          </div>
        ), `<button className="bg-accent text-white">Primary</button>\n<button className="bg-tertiary">Secondary</button>\n<button className="text-secondary">Ghost</button>`)}

        {/* Inputs */}
        {section("Inputs & Forms", "Text inputs, selects, and textareas with theme-aware styling", (
          <div className="space-y-3 max-w-sm">
            <input placeholder="Text input" className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <input type="number" placeholder="Number" className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
            <select className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default">
              <option>Option A</option>
              <option>Option B</option>
            </select>
            <textarea placeholder="Textarea" rows={3} className="w-full px-3 py-2 rounded-lg text-sm bg-tertiary text-primary border-default" />
          </div>
        ), `<input className="px-3 py-2 rounded-lg text-sm"\n  style={{ backgroundColor: "var(--dt-colors-bg-tertiary)",\n    color: "var(--dt-colors-text-primary)",\n    border: "1px solid var(--dt-colors-border-default)" }} />`)}

        {/* Badges */}
        {section("Badges & Tags", "Inline status and label indicators", (
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-accent text-white">Primary</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded btn-secondary-text">Default</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ backgroundColor: "rgba(34,197,94,0.15)", color: "var(--dt-colors-success-default)" }}>Success</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ backgroundColor: "rgba(234,179,8,0.15)", color: "var(--dt-colors-warning-default)" }}>Warning</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-danger-subtle text-danger">Danger</span>
          </div>
        ), `<span className="text-[11px] px-1.5 py-0.5 rounded bg-accent text-white">Label</span>\n<span className="badge badge-success">Success</span>\n<span className="badge badge-warning">Warning</span>`)}

        {/* Skeleton variants */}
        {section("Skeletons", "Loading placeholders for all content shapes", (
          <div className="space-y-3 max-w-md">
            <div className="flex items-center gap-2">
              <SkeletonCircle size={24} />
              <div className="flex-1 space-y-1">
                <Skeleton width="60%" height={12} />
                <Skeleton width="40%" height={12} />
              </div>
            </div>
            <SkeletonText lines={3} />
            <SkeletonCard />
            <SkeletonTableRow cols={4} />
          </div>
        ), `<Skeleton width={24} height={24} rounded="full" />\n<SkeletonCircle size={24} />\n<SkeletonText lines={3} />\n<SkeletonCard />\n<SkeletonTableRow cols={4} />\n<SkeletonCodeBlock lines={5} />`)}

        {/* Cards */}
        {section("Cards & Containers", "Panel, stat card, and surface variants", (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl p-4 card-bordered">
              <div className="text-xs uppercase tracking-wider text-tertiary">Stat</div>
              <div className="text-xl font-bold mt-1">42</div>
            </div>
            <div className="rounded-xl p-4 card-bordered">
              <div className="text-xs uppercase tracking-wider text-tertiary">Cost</div>
              <div className="text-xl font-bold mt-1" style={{ color: "var(--dt-colors-accent-default)" }}>$12.34</div>
            </div>
            <div className="rounded-xl p-4 card-bordered">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4" style={{ color: "var(--dt-colors-accent-default)" }} />
                <span className="text-sm font-medium">Metric</span>
              </div>
              <div className="text-2xl font-bold mt-2">89%</div>
            </div>
          </div>
        ), `<div className="rounded-xl p-4"\n  style={{ backgroundColor: "var(--dt-colors-bg-secondary)",\n    border: "1px solid var(--dt-colors-border-default)" }}>\n  <div className="text-xl font-bold">...</div>\n</div>`)}

        {/* TokenUsageBar */}
        {section("TokenUsageBar", "Compact and expanded token/cost/duration display", (
          <div className="space-y-4">
            <TokenUsageBar inputTokens={342} outputTokens={128} cost={0.00234} durationMs={2340} model="gpt-4o-mini" />
            <TokenUsageBar inputTokens={1200} outputTokens={450} cost={0.00891} durationMs={5100} model="claude-3-haiku" />
            <div className="flex items-center gap-2">
              <span className="text-sm">Inline: </span>
              <TokenUsageBar inputTokens={150} outputTokens={50} cost={0.00042} compact />
            </div>
          </div>
        ), `<TokenUsageBar inputTokens={342} outputTokens={128} cost={0.002} durationMs={2340} model="gpt-4o-mini" />\n<TokenUsageBar inputTokens={150} outputTokens={50} cost={0.00042} compact />`)}

        {/* Icons */}
        {section("Icons (lucide-react)", "All available icons from lucide-react", (
          <div className="grid grid-cols-8 sm:grid-cols-12 gap-3">
            {iconList.map((Icon, i) => (
              <div key={i} className="flex flex-col items-center gap-1 p-2 rounded-lg bg-tertiary">
                <Icon className="w-4 h-4 text-secondary" />
                <span className="text-[8px] text-tertiary">{Icon.displayName || Icon.name || "?"}</span>
              </div>
            ))}
          </div>
        ), `import { Sparkles, Search, Code } from "lucide-react";\n<Sparkles className="w-4 h-4" />`)}

        {/* MessageBubble */}
        {section("MessageBubble", "Chat message component with roles", (
          <div className="space-y-3 max-w-lg">
            <MessageBubble message={{ id: "1", role: "user", content: "What is the capital of France?", created_at: new Date().toISOString() }} />
            <MessageBubble message={{ id: "2", role: "assistant", content: "The capital of France is **Paris**. It is one of the most visited cities in the world.", created_at: new Date().toISOString() }} />
          </div>
        ), `<MessageBubble role="user" content="..." />\n<MessageBubble role="assistant" content="..." />`)}

        {/* Alerts */}
        {section("Alerts & Messages", "Status messages with icons", (
          <div className="space-y-2">
            {[
              { icon: Info, text: "Info message", color: "var(--dt-colors-accent-default)" },
              { icon: CheckCircle, text: "Success message", color: "var(--dt-colors-success-default)" },
              { icon: AlertTriangle, text: "Warning message", color: "var(--dt-colors-warning-default)" },
              { icon: XCircle, text: "Error message", color: "var(--dt-colors-danger-default)" },
            ].map(({ icon: Icon, text, color }, i) => (
              <div key={i} className="flex items-center gap-2 p-3 rounded-lg text-sm" style={{ backgroundColor: `${color}15` }}>
                <Icon className="w-4 h-4 shrink-0" style={{ color }} />
                <span>{text}</span>
              </div>
            ))}
          </div>
        ), `<div className="flex items-center gap-2 p-3 rounded-lg text-sm"\n  style={{ backgroundColor: "rgba(var(--dt-colors-accent-rgb), 0.1)" }}>\n  <Info className="w-4 h-4" style={{ color: "var(--dt-colors-accent-default)" }} />\n  <span>Info message</span>\n</div>`)}

        {/* Progress bars */}
        {section("Progress Bars", "Determinate and indeterminate bars", (
          <div className="space-y-2 max-w-md">
            <div className="w-full h-2 rounded-full bg-primary">
              <div className="h-full rounded-full transition-all" style={{ width: "65%", backgroundColor: "var(--dt-colors-accent-default)" }} />
            </div>
            <div className="w-full h-2 rounded-full bg-primary">
              <div className="h-full rounded-full" style={{ width: "30%", backgroundColor: "var(--dt-colors-warning-default)" }} />
            </div>
            <div className="w-full h-2 rounded-full bg-primary">
              <div className="h-full rounded-full" style={{ width: "85%", backgroundColor: "var(--dt-colors-success-default)" }} />
            </div>
          </div>
        ), `<div className="w-full h-2 rounded-full bg-primary">\n  <div className="h-full rounded-full" style={{ width: "65%", backgroundColor: "var(--dt-colors-accent-default)" }} />\n</div>`)}

        {/* Tab bar */}
        {section("Tab Bar", "Segmented control / tab switcher", (
          <div className="flex gap-1 p-1 rounded-lg max-w-sm bg-tertiary">
            {["Tab 1", "Tab 2", "Tab 3"].map((t, i) => (
              <button key={t} className="flex-1 px-4 py-1.5 rounded-md text-sm font-medium transition-all"
                style={{ backgroundColor: i === 0 ? "var(--dt-colors-accent-default)" : "transparent", color: i === 0 ? "#fff" : "var(--dt-colors-text-secondary)" }}>
                {t}
              </button>
            ))}
          </div>
        ), `<div className="flex gap-1 p-1 rounded-lg bg-tertiary">\n  {tabs.map(t => (\n    <button className="flex-1 px-4 py-1.5 rounded-md text-sm font-medium" {...} />\n  ))}\n</div>`)}

        {/* Code block */}
        {section("Code Block", "Inline and block code styling", (
          <div className="space-y-2 max-w-lg">
            <p>Inline code: <code className="px-1.5 py-0.5 rounded text-xs font-mono" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-accent-default)" }}>npm run dev</code></p>
            <pre className="p-3 rounded-lg text-xs font-mono overflow-x-auto" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-secondary)", border: "1px solid var(--dt-colors-border-default)" }}>
{`function hello() {
  console.log("Hello, World!");
}`}
            </pre>
          </div>
        ), `<code className="px-1.5 py-0.5 rounded text-xs font-mono">...</code>\n<pre className="p-3 rounded-lg text-xs font-mono">...</pre>`)}
      </div>
    </div>
  );
}
