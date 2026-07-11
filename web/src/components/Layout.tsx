import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";
import { useTheme } from "../design/ThemeContext";
import PWAInstallPrompt from "./PWAInstallPrompt";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/chat", label: "Chat" },
  { to: "/admin", label: "Admin" },
  { to: "/tasks", label: "Tasks" },
  { to: "/workflows", label: "Workflows" },
  { to: "/monitors", label: "Monitors" },
  { to: "/routines", label: "Routines" },
  { to: "/code", label: "Code" },
  { to: "/ide", label: "IDE" },
  { to: "/git", label: "Git" },
  { to: "/github", label: "GitHub" },
  { to: "/cicd", label: "CI/CD" },
  { to: "/tests", label: "Tests" },
  { to: "/media", label: "Media" },
  { to: "/browser", label: "Browser" },
  { to: "/web-search", label: "Search" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/analytics", label: "Analytics" },
  { to: "/abtesting", label: "A/B Test" },
  { to: "/cost", label: "Cost" },
  { to: "/voice", label: "Voice" },
  { to: "/collab", label: "Collab" },
  { to: "/rag", label: "RAG" },
  { to: "/finetune", label: "FineTune" },
  { to: "/chaos", label: "Chaos" },
  { to: "/email", label: "Email" },
  { to: "/plugins", label: "Plugins" },
  { to: "/settings", label: "System" },
];

export default function Layout() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-primary)" }}>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-10 md:hidden"
          style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed md:static z-20 w-56 flex flex-col flex-shrink-0 border-r transition-transform duration-200 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
        style={{
          backgroundColor: "var(--dt-colors-bg-secondary)",
          borderColor: "var(--dt-colors-border-default)",
        }}
      >
        <div
          className="p-4 border-b"
          style={{ borderColor: "var(--dt-colors-border-default)" }}
        >
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold">Raven AI</h1>
            <button
              className="md:hidden text-sm"
              style={{ color: "var(--dt-colors-text-tertiary)" }}
              onClick={() => setSidebarOpen(false)}
            >
              ✕
            </button>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${
                  isActive ? "border" : ""
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? {
                      backgroundColor: "var(--dt-colors-accent-muted)",
                      color: "var(--dt-colors-accent-default)",
                      borderColor: "var(--dt-colors-accent-subtle)",
                    }
                  : {
                      color: "var(--dt-colors-text-secondary)",
                    }
              }
            >
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div
          className="p-3 border-t space-y-2"
          style={{ borderColor: "var(--dt-colors-border-default)" }}
        >
          <button
            onClick={toggleTheme}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition"
            style={{
              color: "var(--dt-colors-text-secondary)",
              backgroundColor: "var(--dt-colors-bg-tertiary)",
            }}
          >
            {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
          </button>
          <button
            onClick={handleLogout}
            className="w-full text-center text-xs transition font-medium"
            style={{ color: "var(--dt-colors-text-tertiary)" }}
          >
            Sign Out
          </button>
          <div
            className="text-[10px] text-center"
            style={{ color: "var(--dt-colors-border-hover)" }}
          >
            Raven AI v{import.meta.env.VITE_APP_VERSION || "0.2.0"}
          </div>
        </div>
      </aside>

      <main
        className="flex-1 overflow-y-auto min-w-0"
        style={{ backgroundColor: "var(--dt-colors-bg-primary)" }}
      >
        <div className="flex items-center gap-2 p-2 md:hidden border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded text-lg"
            style={{ color: "var(--dt-colors-text-secondary)" }}
          >
            ☰
          </button>
          <span className="text-sm font-semibold">Raven AI</span>
        </div>
        <div className="max-w-6xl mx-auto p-4 md:p-6">
          <Outlet />
        </div>
      </main>

      <PWAInstallPrompt />
    </div>
  );
}
