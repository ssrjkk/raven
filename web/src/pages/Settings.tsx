import { useState, useEffect } from "react";
import { api } from "../api/client";

export default function Settings() {
  const [config, setConfig] = useState<Record<string, string>>({});
  const [shuttingDown, setShuttingDown] = useState(false);

  useEffect(() => {
    api.config().then(setConfig).catch(() => {});
  }, []);

  async function handleShutdown() {
    if (window.confirm("Shutdown Raven AI?")) {
      setShuttingDown(true);
      try {
        await api.shutdown();
      } catch {}
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Configuration</h2>
        <div className="space-y-2 text-sm">
          {Object.entries(config).map(([k, v]) => (
            <div key={k} className="flex justify-between py-1 border-b border-gray-800/30">
              <span className="text-gray-500">{k}</span>
              <span className="text-gray-200 font-mono">{String(v).slice(0, 40)}</span>
            </div>
          ))}
        </div>
      </div>

      <button onClick={handleShutdown} disabled={shuttingDown}
        className="bg-red-700 hover:bg-red-600 disabled:bg-red-900/50 text-white px-5 py-2 rounded-xl text-sm font-medium transition">
        {shuttingDown ? "Shutting down..." : "Shutdown Raven"}
      </button>
    </div>
  );
}
