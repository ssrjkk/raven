import { Link } from "react-router-dom";
import { Session } from "../api/client";

interface SidebarProps {
  sessions: Session[];
  currentSession: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

const channelIcon: Record<string, string> = {
  telegram: "T",
  discord: "D",
  webchat: "W",
  slack: "#",
  matrix: "M",
};

export default function Sidebar({ sessions, currentSession, onSelect, onNew }: SidebarProps) {
  return (
    <aside className="w-72 bg-gray-900/80 border-r border-gray-800/50 flex flex-col">
      <div className="p-4 border-b border-gray-800/50 flex items-center justify-between">
        <h1 className="text-lg font-bold">Raven</h1>
        <button
          onClick={onNew}
          className="text-gray-400 hover:text-white p-1.5 rounded-lg hover:bg-gray-800 transition"
          title="New session"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        <div className="text-xs text-gray-600 uppercase tracking-wider px-3 py-2 font-medium">
          Sessions
        </div>
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition
              ${s.id === currentSession
                ? "bg-violet-600/20 text-violet-200 border border-violet-500/20"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
              }`}
          >
            <span className="text-xs font-mono w-5 text-center">{channelIcon[s.channel] || "?"}</span>
            <span className="truncate flex-1 text-left font-mono text-xs">
              {s.id.split(":").slice(0, 2).join(":").slice(-24)}
            </span>
            <span className="text-[10px] text-gray-600">
              {new Date(s.updated_at).toLocaleDateString()}
            </span>
          </button>
        ))}
        {sessions.length === 0 && (
          <p className="text-xs text-gray-600 text-center py-8">
            No sessions yet. Start a conversation!
          </p>
        )}
      </div>
      <div className="p-3 border-t border-gray-800/50 space-y-1">
        <Link
          to="/ide"
          className="block text-center text-[11px] text-violet-400 hover:text-violet-300 transition font-medium"
        >
          Open AI-OS IDE
        </Link>
        <div className="text-[10px] text-gray-600 text-center space-y-1">
          <div>Telegram: @ssrjkk</div>
          <div>GitHub: github.com/ssrjkk</div>
          <div>Email: ray013lefe@gmail.com</div>
        </div>
        <div className="text-[10px] text-gray-700 text-center">
          Raven AI v0.1.0
        </div>
      </div>
    </aside>
  );
}
