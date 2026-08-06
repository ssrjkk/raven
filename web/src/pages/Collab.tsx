import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";
import PageHeader from "../components/PageHeader";

interface CollabUser {
  id: string;
  name: string;
}

interface CollabComment {
  id: string;
  user_id: string;
  line: number;
  text: string;
  resolved: boolean;
}

interface CollabSession {
  session_id: string;
  file_path: string;
  connected_users: number;
  users: number | CollabUser[];
  version: string;
}

interface CollabSessionDetails {
  session_id: string;
  file_path: string;
  connected_users: number;
  users: number | CollabUser[];
  version: string;
  content?: string;
  comments?: CollabComment[];
}

type Tab = "sessions" | "session";

export default function Collab() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("sessions");
  const [selectedSession, setSelectedSession] = useState<CollabSessionDetails | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // create form
  const [sessionId, setSessionId] = useState("");
  const [filePath, setFilePath] = useState("");
  // join form
  const [joinSid, setJoinSid] = useState("");
  const [joinUid, setJoinUid] = useState("");
  const [joinName, setJoinName] = useState("");

  const { data: sessionsData } = useApiQuery<{ sessions: CollabSession[] }>(["collabSessions"], () => api.collabSessions(), { enabled: tab === "sessions" });
  const sessions = sessionsData?.sessions ?? [];

  const { data: sessionDetail } = useApiQuery<CollabSessionDetails>(["collabSession", selectedSession?.session_id ?? ""], () => api.collabSession(selectedSession!.session_id), { enabled: tab === "session" && !!selectedSession });

  const createSession = useMutation({
    mutationFn: () => api.collabCreateSession(sessionId, filePath),
    onSuccess: (r) => {
      setMsg(`Session '${r.session_id}' created`);
      setSessionId(""); setFilePath("");
      qc.invalidateQueries({ queryKey: ["collabSessions"] });
    },
    onError: (e: any) => setError(e.message || "Create failed"),
  });

  const joinSession = useMutation({
    mutationFn: () => api.collabJoin(joinSid, joinUid, joinName),
    onSuccess: () => {
      setMsg(`Joined session '${joinSid}'`);
      qc.invalidateQueries({ queryKey: ["collabSessions"] });
    },
    onError: (e: any) => setError(e.message || "Join failed"),
  });

  return (
    <div>
      <PageHeader title="Collaboration" subtitle="Live code sessions and collaborative review" />

      <div className="flex gap-1 mb-6 border-b border-default">
        <button onClick={() => setTab("sessions")}
          className={`px-4 py-2 text-sm font-medium rounded-t-lg transition ${tab === "sessions" ? "tab-active" : "tab-inactive"}`}>
          Sessions
        </button>
        <button onClick={() => setTab("session")} disabled={!selectedSession}
          className={`px-4 py-2 text-sm font-medium rounded-t-lg transition disabled:opacity-50 ${tab === "session" ? "tab-active" : "tab-inactive"}`}>
          Session Details
        </button>
      </div>

      {error && <div className="p-3 mb-4 rounded-lg text-sm bg-danger-muted text-danger">{error}</div>}
      {msg && <div className="p-3 mb-4 rounded-lg text-sm bg-success-muted text-success">{msg}</div>}

      {tab === "sessions" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Create Session</h2>
              <div className="space-y-3 mb-3">
                <input placeholder="Session ID" value={sessionId} onChange={e => setSessionId(e.target.value)}
                  className="input-base" />
                <input placeholder="File path" value={filePath} onChange={e => setFilePath(e.target.value)}
                  className="input-base" />
              </div>
              <button onClick={() => createSession.mutate()} disabled={createSession.isPending || !sessionId || !filePath}
                className="btn-primary">
                {createSession.isPending ? "..." : "Create Session"}
              </button>
            </div>

            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Join Session</h2>
              <div className="space-y-3 mb-3">
                <input placeholder="Session ID" value={joinSid} onChange={e => setJoinSid(e.target.value)}
                  className="input-base" />
                <input placeholder="User ID" value={joinUid} onChange={e => setJoinUid(e.target.value)}
                  className="input-base" />
                <input placeholder="User Name" value={joinName} onChange={e => setJoinName(e.target.value)}
                  className="input-base" />
              </div>
              <button onClick={() => joinSession.mutate()} disabled={joinSession.isPending || !joinSid || !joinUid}
                className="btn-primary">
                Join Session
              </button>
            </div>
          </div>

          <div className="card p-4">
            <h2 className="text-lg font-semibold mb-3">Active Sessions ({sessions.length})</h2>
            {sessions.length === 0 ? (
              <p className="text-sm text-tertiary">No active sessions.</p>
            ) : (
              <div className="space-y-2">
                {sessions.map((s) => (
                  <div key={s.session_id}
                    onClick={() => { setSelectedSession(s); setTab("session"); }}
                    className="flex items-center justify-between p-3 rounded-lg cursor-pointer bg-tertiary">
                    <div>
                      <span className="font-medium">{s.session_id}</span>
                      <span className="ml-3 text-sm text-tertiary">{s.file_path}</span>
                    </div>
                    <span className="text-xs text-tertiary">{s.connected_users}/{typeof s.users === "number" ? s.users : s.users.length} users v{s.version}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "session" && selectedSession && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="card p-4">
            <h2 className="text-lg font-semibold mb-3">Document Content</h2>
            <pre className="p-3 rounded-lg text-xs overflow-auto max-h-96 bg-tertiary">
              {sessionDetail?.content || "(empty)"}
            </pre>
          </div>
          <div className="space-y-4">
            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Users</h2>
              {Array.isArray(sessionDetail?.users) && (sessionDetail!.users as CollabUser[]).map((u: CollabUser) => (
                <div key={u.id} className="p-2 rounded-lg text-sm mb-1 bg-tertiary">
                  {u.name} ({u.id})
                </div>
              ))}
            </div>
            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Comments</h2>
              {sessionDetail?.comments?.length === 0 && <p className="text-sm text-tertiary">No comments.</p>}
              {sessionDetail?.comments?.map((c) => (
                <div key={c.id} className="p-2 rounded-lg text-sm mb-1 bg-tertiary">
                  <span className="font-medium">{c.user_id}</span> L{c.line}: {c.text}
                  <span className="ml-2 text-xs">{c.resolved ? "✓ resolved" : "✗ open"}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
