import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";
import { useTheme } from "../design/ThemeContext";

const nav = [
  { to: "/", label: "Dashboard" },
  { to: "/chat", label: "Chat" },
  { to: "/admin", label: "Admin" },
  { to: "/tasks", label: "Tasks" },
  { to: "/monitors", label: "Monitors" },
  { to: "/routines", label: "Routines" },
  { to: "/code", label: "Code" },
  { to: "/ide", label: "IDE" },
  { to: "/settings", label: "System" },
];

export default function Layout() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: "var(--dt-colors-bg-primary)", color: "var(--dt-colors-text-primary)" }}>
      <aside
        className="w-56 flex flex-col flex-shrink-0 border-r"
        style={{
          backgroundColor: "var(--dt-colors-bg-secondary)",
          borderColor: "var(--dt-colors-border-default)",
        }}
      >
        <div
          className="p-4 border-b"
          style={{ borderColor: "var(--dt-colors-border-default)" }}
        >
          <h1 className="text-lg font-bold">Raven AI</h1>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${
                  isActive
                    ? "border"
                    : ""
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
        className="flex-1 overflow-y-auto"
        style={{ backgroundColor: "var(--dt-colors-bg-primary)" }}
      >
        <div className="max-w-6xl mx-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
