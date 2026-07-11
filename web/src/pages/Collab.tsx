import { useEffect, useState } from "react";
import { api } from "../api/client";

type Tab = "sessions" | "session";

export default function Collab() {
  const [tab, setTab] = useState<Tab>("sessions");
  const [sessions, setSessions] = useState<any[]>([]);
  const [selectedSession, setSelectedSession] = useState<any>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  // create form
  const [sessionId, setSessionId] = useState("");
  const [filePath, setFilePath] = useState("");
  // join form
  const [joinSid, setJoinSid] = useState("");
  const [joinUid, setJoinUid] = useState("");
  const [joinName, setJoinName] = useState("");

  async function loadSessions() {
    setLoading(true); setError("");
    try {
      const r = await api.collabSessions();
      setSessions(r.sessions);
    } catch (e: any) {
      setError(e.message || "Failed to load sessions");
    } finally { setLoading(false); }
  }

  async function loadSession(sid: string) {
    setLoading(true); setError("");
    try {
      const r = await api.collabSession(sid);
      setSelectedSession(r);
    } catch (e: any) {
      setError(e.message || "Failed to load session");
    } finally { setLoading(false); }
  }

  useEffect(() => { if (tab === "sessions") loadSessions(); }, [tab]);

  async function handleCreate() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      const r: any = await api.collabCreateSession(sessionId, filePath);
      setMsg(`Session '${r.session_id}' created`);
      setSessionId(""); setFilePath("");
      loadSessions();
    } catch (e: any) {
      setError(e.message || "Create failed");
    } finally { setLoading(false); }
  }

  async function handleJoin() {
    setMsg(""); setError("");
    setLoading(true);
    try {
      await api.collabJoin(joinSid, joinUid, joinName);
      setMsg(`Joined session '${joinSid}'`);
      loadSessions();
    } catch (e: any) {
      setError(e.message || "Join failed");
    } finally { setLoading(false); }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Collaboration</h1>

      <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--dt-colors-border-default)" }}>
        <button onClick={() => setTab("sessions")} className="px-4 py-2 text-sm font-medium rounded-t-lg transition"
          style={{ color: tab === "sessions" ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === "sessions" ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
          Sessions
        </button>
        <button onClick={() => setTab("session")} disabled={!selectedSession} className="px-4 py-2 text-sm font-medium rounded-t-lg transition disabled:opacity-50"
          style={{ color: tab === "session" ? "var(--dt-colors-accent-default)" : "var(--dt-colors-text-secondary)", borderBottom: tab === "session" ? "2px solid var(--dt-colors-accent-default)" : "2px solid transparent" }}>
          Session Details
        </button>
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--dt-colors-danger-default)" }}>{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm" style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--dt-colors-success-default)" }}>{msg}</div>}

      {tab === "sessions" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <h2 className="text-lg font-semibold mb-3">Create Session</h2>
              <div className="space-y-3 mb-3">
                <input placeholder="Session ID" value={sessionId} onChange={e => setSessionId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                <input placeholder="File path" value={filePath} onChange={e => setFilePath(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              </div>
              <button onClick={handleCreate} disabled={loading || !sessionId || !filePath}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                {loading ? "..." : "Create Session"}
              </button>
            </div>

            <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <h2 className="text-lg font-semibold mb-3">Join Session</h2>
              <div className="space-y-3 mb-3">
                <input placeholder="Session ID" value={joinSid} onChange={e => setJoinSid(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                <input placeholder="User ID" value={joinUid} onChange={e => setJoinUid(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
                <input placeholder="User Name" value={joinName} onChange={e => setJoinName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)", color: "var(--dt-colors-text-primary)", border: "1px solid var(--dt-colors-border-default)" }} />
              </div>
              <button onClick={handleJoin} disabled={loading || !joinSid || !joinUid}
                className="px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50" style={{ backgroundColor: "var(--dt-colors-accent-default)", color: "#fff" }}>
                Join Session
              </button>
            </div>
          </div>

          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Active Sessions ({sessions.length})</h2>
            {sessions.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No active sessions.</p>
            ) : (
              <div className="space-y-2">
                {sessions.map((s: any) => (
                  <div key={s.session_id}
                    onClick={() => { setSelectedSession(s); setTab("session"); loadSession(s.session_id); }}
                    className="flex items-center justify-between p-3 rounded-lg cursor-pointer" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                    <div>
                      <span className="font-medium">{s.session_id}</span>
                      <span className="ml-3 text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.file_path}</span>
                    </div>
                    <span className="text-xs" style={{ color: "var(--dt-colors-text-tertiary)" }}>{s.connected_users}/{s.users} users v{s.version}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "session" && selectedSession && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
            <h2 className="text-lg font-semibold mb-3">Document Content</h2>
            <pre className="p-3 rounded-lg text-xs overflow-auto max-h-96" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
              {selectedSession.content || "(empty)"}
            </pre>
          </div>
          <div className="space-y-4">
            <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <h2 className="text-lg font-semibold mb-3">Users</h2>
              {selectedSession.users?.map((u: any) => (
                <div key={u.id} className="p-2 rounded-lg text-sm mb-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  {u.name} ({u.id})
                </div>
              ))}
            </div>
            <div className="p-4 rounded-lg" style={{ backgroundColor: "var(--dt-colors-bg-secondary)" }}>
              <h2 className="text-lg font-semibold mb-3">Comments</h2>
              {selectedSession.comments?.length === 0 && <p className="text-sm" style={{ color: "var(--dt-colors-text-tertiary)" }}>No comments.</p>}
              {selectedSession.comments?.map((c: any) => (
                <div key={c.id} className="p-2 rounded-lg text-sm mb-1" style={{ backgroundColor: "var(--dt-colors-bg-tertiary)" }}>
                  <span className="font-medium">{c.user_id}</span> L{c.line}: {c.text}
                  <span className="ml-2 text-xs">{c.resolved ? "✓ resolved" : "○ open"}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
