import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, setToken } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const navigate = useNavigate();

  const { data: providersData } = useApiQuery<{ providers: { name: string; icon: string; enabled: boolean }[] }>(["oauthProviders"], () => api.oauthProviders());
  const providers = (providersData?.providers ?? []).filter((p) => p.enabled);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = isRegister
        ? await api.register(username, password)
        : await api.login(username, password);
      setToken(data.token);
      navigate("/");
    } catch (err) {
      setError(isRegister ? "Registration failed" : "Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  async function handleOAuth(provider: string) {
    try {
      const r = await api.oauthAuthorize(provider, window.location.origin + "/login");
      const popup = window.open(r.url, "oauth", "width=600,height=700");
      if (!popup) {
        setError("Pop-up blocked. Allow pop-ups for this site.");
        return;
      }
      const handler = (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return;
        if (event.data?.type === "oauth_callback") {
          window.removeEventListener("message", handler);
          setToken(event.data.token);
          navigate("/");
        }
      };
      window.addEventListener("message", handler);
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="bg-gray-900/60 border border-gray-800/50 rounded-2xl p-8 w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Raven AI</h1>
          <p className="text-sm text-gray-500 mt-1">
            {isRegister ? "Create an account" : "Sign in to your account"}
          </p>
        </div>

        {providers.length > 0 && (
          <div className="space-y-2">
            {providers.map((p) => (
              <button
                key={p.name}
                onClick={() => handleOAuth(p.name)}
                className="w-full flex items-center justify-center gap-2 bg-gray-800/60 hover:bg-gray-800 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 transition"
              >
                <span className="font-bold text-violet-400">{p.icon}</span>
                <span>Continue with {p.name.charAt(0).toUpperCase() + p.name.slice(1)}</span>
              </button>
            ))}
            <div className="flex items-center gap-3 py-2">
              <div className="flex-1 h-px bg-gray-800" />
              <span className="text-xs text-gray-600">or</span>
              <div className="flex-1 h-px bg-gray-800" />
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="text-xs text-gray-500 block mb-1">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="text-xs text-gray-500 block mb-1">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50"
              required
            />
          </div>
          {error && (
            <p className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-violet-600 hover:bg-violet-500 disabled:bg-violet-800/50 text-white py-2 rounded-lg text-sm font-medium transition"
          >
            {loading ? "Please wait..." : isRegister ? "Register" : "Sign In"}
          </button>
        </form>

        <p className="text-xs text-gray-500 text-center">
          {isRegister ? "Already have an account? " : "Don't have an account? "}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="text-violet-400 hover:text-violet-300"
          >
            {isRegister ? "Sign in" : "Register"}
          </button>
        </p>
      </div>
    </div>
  );
}
