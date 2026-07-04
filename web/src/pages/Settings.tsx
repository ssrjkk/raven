import { useState, useEffect } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";

export default function Settings() {
  const [config, setConfig] = useState<Record<string, string>>({});
  const [shuttingDown, setShuttingDown] = useState(false);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => {
    api.config().then(setConfig).catch((e: unknown) => { console.error("Failed to load config:", e); toast("Failed to load config", "error"); })
      .finally(() => setLoading(false));
  }, []);

  async function handleShutdown() {
    if (window.confirm("Shutdown Raven AI? This will stop the server.")) {
      setShuttingDown(true);
      try {
        await api.shutdown();
        toast("Server shutting down...", "info");
      } catch (e) {
        console.error("Shutdown failed:", e);
        toast("Shutdown failed", "error");
        setShuttingDown(false);
      }
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <div className="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4 animate-pulse">
          <div className="h-4 bg-gray-800 rounded w-24 mb-4" />
          {[1, 2, 3].map((i) => <div key={i} className="h-8 bg-gray-800/50 rounded mb-2" />)}
        </div>
      </div>
    );
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