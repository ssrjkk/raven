import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../api/client";

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

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="flex h-screen">
      <aside className="w-56 bg-gray-900/90 border-r border-gray-800/50 flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-gray-800/50">
          <h1 className="text-lg font-bold">
            Raven AI
          </h1>
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
                    ? "bg-violet-600/20 text-violet-200 border border-violet-500/20"
                    : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
                }`
              }
            >
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-gray-800/50 space-y-2">
          <button onClick={handleLogout}
            className="w-full text-center text-xs text-gray-500 hover:text-red-400 transition font-medium">
            Sign Out
          </button>
          <div className="text-[10px] text-gray-700 text-center">
            Raven AI v{import.meta.env.VITE_APP_VERSION || "0.2.0"}
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-gray-950">
        <div className="max-w-6xl mx-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}