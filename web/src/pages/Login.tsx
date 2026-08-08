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
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden px-4">
      <div
        className="absolute -top-32 -right-24 w-96 h-96 rounded-full pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(closest-side, var(--dt-colors-accent-muted, rgba(124,58,237,0.35)), transparent)",
        }}
      />
      <div
        className="absolute -bottom-40 -left-24 w-[28rem] h-[28rem] rounded-full pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(closest-side, var(--dt-colors-accent-subtle, rgba(217,70,239,0.18)), transparent)",
        }}
      />

      <div className="card rounded-2xl p-8 w-full max-w-sm space-y-6 relative">
        <div className="text-center space-y-2">
          <div
            className="mx-auto w-12 h-12 rounded-xl flex items-center justify-center text-white font-black text-2xl shadow-lg"
            style={{
              backgroundImage: "linear-gradient(135deg, var(--dt-colors-accent-default, #7c3aed), #d946ef)",
              boxShadow: "0 8px 24px var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.35))",
            }}
          >
            R
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Raven AI</h1>
          <p className="text-sm text-tertiary">
            {isRegister ? "Create an account" : "Sign in to your account"}
          </p>
        </div>

        {providers.length > 0 && (
          <div className="space-y-2">
            {providers.map((p) => (
              <button
                key={p.name}
                onClick={() => handleOAuth(p.name)}
                className="btn-outline w-full"
              >
                <span className="font-bold" style={{ color: "var(--dt-colors-accent-default)" }}>{p.icon}</span>
                <span>Continue with {p.name.charAt(0).toUpperCase() + p.name.slice(1)}</span>
              </button>
            ))}
            <div className="flex items-center gap-3 py-2">
              <div className="flex-1 h-px" style={{ backgroundColor: "var(--dt-colors-border-default)" }} />
              <span className="text-xs text-tertiary">or</span>
              <div className="flex-1 h-px" style={{ backgroundColor: "var(--dt-colors-border-default)" }} />
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="text-xs text-tertiary block mb-1.5">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input-base w-full"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="text-xs text-tertiary block mb-1.5">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-base w-full"
              required
            />
          </div>
          {error && (
            <p
              className="text-xs rounded-lg px-3 py-2 flex items-center gap-2"
              style={{
                color: "var(--dt-colors-status-error)",
                backgroundColor: "var(--dt-colors-status-error-bg)",
                border: "1px solid var(--dt-colors-status-error)",
              }}
            >
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
          >
            {loading ? "Please wait..." : isRegister ? "Register" : "Sign In"}
          </button>
        </form>

        <p className="text-xs text-tertiary text-center">
          {isRegister ? "Already have an account? " : "Don't have an account? "}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="font-medium"
            style={{ color: "var(--dt-colors-accent-default)" }}
          >
            {isRegister ? "Sign in" : "Register"}
          </button>
        </p>
      </div>
    </div>
  );
}
