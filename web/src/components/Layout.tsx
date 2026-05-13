import { NavLink, Outlet } from "react-router-dom";

const nav = [
  { to: "/", label: "Dashboard", icon: "◉" },
  { to: "/chat", label: "Chat", icon: "💬" },
  { to: "/tasks", label: "Tasks", icon: "📋" },
  { to: "/monitors", label: "Monitors", icon: "📊" },
  { to: "/routines", label: "Routines", icon: "⏰" },
  { to: "/code", label: "Code", icon: "💻" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export default function Layout() {
  return (
    <div className="flex h-screen">
      <aside className="w-56 bg-gray-900/90 border-r border-gray-800/50 flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-gray-800/50">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <span>🐦</span> Raven AI
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
              <span className="text-base">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-gray-800/50 text-[10px] text-gray-700 text-center">
          Raven AI v0.2.0
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
