import {
  Activity,
  BarChart3,
  Blocks,
  Bomb,
  BookOpen,
  Braces,
  Clapperboard,
  Code2,
  Database,
  FlaskConical,
  FolderGit2,
  Gauge,
  GitBranch,
  GitFork,
  GitMerge,
  Globe,
  History,
  LayoutDashboard,
  Lightbulb,
  ListTodo,
  type LucideIcon,
  Mail,
  MessageSquare,
  Mic,
  Moon,
  MoonStar,
  Palette,
  Puzzle,
  RefreshCw,
  Search,
  Settings,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Split,
  Sun,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Suspense, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { clearToken } from "../api/client";
import { type Theme, useTheme } from "../design/ThemeContext";
import { ErrorBoundary } from "./ErrorBoundary";
import PWAInstallPrompt from "./PWAInstallPrompt";
import { SkeletonPage } from "./Skeleton";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "Overview",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/chat", label: "Chat", icon: MessageSquare },
      { to: "/chat/history", label: "History", icon: History },
      { to: "/admin", label: "Admin", icon: Shield },
    ],
  },
  {
    title: "Automate",
    items: [
      { to: "/tasks", label: "Tasks", icon: ListTodo },
      { to: "/workflows", label: "Workflows", icon: Workflow },
      { to: "/monitors", label: "Monitors", icon: Activity },
      { to: "/routines", label: "Routines", icon: RefreshCw },
    ],
  },
  {
    title: "Develop",
    items: [
      { to: "/code", label: "Code", icon: Code2 },
      { to: "/ide", label: "IDE", icon: Braces },
      { to: "/git", label: "Git", icon: GitBranch },
      { to: "/github", label: "GitHub", icon: GitFork },
      { to: "/cicd", label: "CI/CD", icon: GitMerge },
      { to: "/tests", label: "Tests", icon: FlaskConical },
    ],
  },
  {
    title: "Explore",
    items: [
      { to: "/dream", label: "Dream", icon: Sparkles },
      { to: "/media", label: "Media", icon: Clapperboard },
      { to: "/browser", label: "Browser", icon: Globe },
      { to: "/web-search", label: "Search", icon: Search },
      { to: "/knowledge", label: "Knowledge", icon: BookOpen },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
      { to: "/insights", label: "Insights", icon: Lightbulb },
      { to: "/project-insights", label: "Project Insights", icon: FolderGit2 },
    ],
  },
  {
    title: "Build",
    items: [
      { to: "/scaffold", label: "Scaffold", icon: Blocks },
      { to: "/code-quality", label: "Code Quality", icon: Gauge },
      { to: "/abtesting", label: "A/B Test", icon: Split },
      { to: "/cost", label: "Cost", icon: Wallet },
      { to: "/voice", label: "Voice", icon: Mic },
      { to: "/collab", label: "Collab", icon: Users },
      { to: "/rag", label: "RAG", icon: Database },
      { to: "/finetune", label: "FineTune", icon: SlidersHorizontal },
      { to: "/chaos", label: "Chaos", icon: Bomb },
      { to: "/email", label: "Email", icon: Mail },
      { to: "/plugins", label: "Plugins", icon: Puzzle },
    ],
  },
  {
    title: "Preferences",
    items: [
      { to: "/components", label: "UI Kit", icon: Palette },
      { to: "/settings", label: "System", icon: Settings },
    ],
  },
];

function openCommandPalette() {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }));
}

const THEME_TARGETS: Record<Theme, { label: string; icon: LucideIcon }> = {
  dark: { label: "Light", icon: Sun },
  light: { label: "Midnight", icon: MoonStar },
  midnight: { label: "Dark", icon: Moon },
};

function ThemeToggleButton({ theme, onClick }: { theme: Theme; onClick: () => void }) {
  const target = THEME_TARGETS[theme];
  const Icon = target.icon;
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition"
      style={{
        color: "var(--dt-colors-text-secondary)",
        backgroundColor: "var(--dt-colors-bg-tertiary)",
      }}
      title={`Switch to ${target.label} theme`}
    >
      <Icon size={15} className="shrink-0" />
      {target.label}
    </button>
  );
}

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div
      className="flex h-screen"
      style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-primary)" }}
    >
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-10 md:hidden"
          style={{ backgroundColor: "rgba(0,0,0,0.5)", backdropFilter: "blur(2px)" }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed md:static z-20 w-60 flex flex-col flex-shrink-0 border-r transition-transform duration-200 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
        style={{
          backgroundColor: "var(--dt-colors-bg-secondary)",
          borderColor: "var(--dt-colors-border-default)",
        }}
      >
        {/* Brand */}
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-default">
          <div
            className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-white font-black text-lg shadow-lg"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default, #7c3aed), #d946ef)",
              boxShadow: "0 4px 14px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.35))",
            }}
          >
            R
          </div>
          <div className="min-w-0">
            <h1 className="text-base font-bold leading-tight tracking-tight">Raven AI</h1>
            <span className="text-[10px] text-tertiary">command & control</span>
          </div>
          <button
            className="md:hidden ml-auto text-tertiary text-sm"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            ✕
          </button>
        </div>

        {/* Command palette trigger */}
        <button
          onClick={openCommandPalette}
          className="mx-3 mt-3 flex items-center gap-2 px-3 py-2 rounded-lg border border-default text-sm transition hover:border-accent-muted"
          style={{ backgroundColor: "var(--dt-colors-bg-primary)" }}
        >
          <Search size={14} className="shrink-0" />
          <span className="text-xs text-tertiary flex-1 text-left">Search…</span>
          <kbd className="kbd">⌘K</kbd>
        </button>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-3">
          {navSections.map((section) => (
            <div key={section.title}>
              <div className="nav-section-label">{section.title}</div>
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    onClick={() => setSidebarOpen(false)}
                    className="relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition group"
                    style={({ isActive }) =>
                      isActive
                        ? {
                            backgroundColor: "var(--dt-colors-accent-muted)",
                            color: "var(--dt-colors-accent-default)",
                          }
                        : {
                            color: "var(--dt-colors-text-secondary)",
                          }
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <span
                            className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-full"
                            style={{ backgroundColor: "var(--dt-colors-accent-default)" }}
                          />
                        )}
                        <item.icon size={16} className="shrink-0" />
                        <span className="truncate">{item.label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-3 border-t space-y-2 border-default">
          <ThemeToggleButton theme={theme} onClick={toggleTheme} />
          <button
            onClick={handleLogout}
            className="w-full text-center text-xs transition font-medium text-tertiary"
          >
            Sign Out
          </button>
          <div className="text-[10px] text-center" style={{ color: "var(--dt-colors-border-hover)" }}>
            Raven AI v{import.meta.env.VITE_APP_VERSION || "0.2.0"}
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto min-w-0 bg-primary">
        <div className="flex items-center gap-2 p-2 md:hidden border-b border-default">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded text-lg text-secondary"
            aria-label="Open sidebar"
          >
            ☰
          </button>
          <span className="text-sm font-semibold">Raven AI</span>
        </div>
        <div className="max-w-6xl mx-auto p-4 md:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
            >
              <Suspense fallback={<SkeletonPage sections={[{ type: "card" }, { type: "text" }, { type: "table" }]} />}>
                <ErrorBoundary>
                  <Outlet />
                </ErrorBoundary>
              </Suspense>
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      <PWAInstallPrompt />
    </div>
  );
}
