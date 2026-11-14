import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { CollabSessionInfo } from "../api/types";
import PageHeader from "../components/PageHeader";
import { useApiQuery } from "../hooks/useApiQuery";
import { useCollabSocket } from "../hooks/useCollabSocket";
import { offsetToPos, unitsToPoints } from "../lib/collab";
import { errorMessage } from "../lib/errors";

type Tab = "sessions" | "session";

export default function Collab() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("sessions");
  // A row of the list, kept so the details tab can name the file before its own fetch lands.
  const [selectedSession, setSelectedSession] = useState<CollabSessionInfo | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  // create form
  const [sessionId, setSessionId] = useState("");
  const [filePath, setFilePath] = useState("");
  // join form
  const [joinSid, setJoinSid] = useState("");
  const [joinUid, setJoinUid] = useState("");
  const [joinName, setJoinName] = useState("");

  const { data: sessionsData } = useApiQuery(["collabSessions"], () => api.collabSessions(), { enabled: tab === "sessions" });
  const sessions = sessionsData?.sessions ?? [];

  // Comments, presence and the document all arrive on the socket, so the REST snapshot is only the
  // way to learn the session's file path before that socket opens.
  const { data: sessionDetail } = useApiQuery(["collabSession", selectedSession?.session_id ?? ""], () => api.collabSession(selectedSession!.session_id), { enabled: tab === "session" && !!selectedSession });

  // Only the Session Details tab holds a socket: opening one per row in the list would put a
  // long-lived connection on every session the console is merely naming.
  const liveSessionId = tab === "session" && selectedSession ? selectedSession.session_id : null;
  const liveFile = selectedSession?.file_path ?? "";
  const { doc, connected, publish, sendCursor } = useCollabSocket(liveSessionId, liveFile);

  const [draft, setDraft] = useState<string | null>(null);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  // Until the first `state` frame the snapshot already fetched is what the editor holds; after it the
  // gateway's document is the only source, so the page never edits a copy it cannot publish.
  const base = doc.loaded ? doc.content : sessionDetail?.content ?? "";
  const shown = draft ?? base;
  const dirty = draft !== null && draft !== base;
  // The roster and the review thread come off the socket once it has spoken; until then the snapshot
  // this page already fetched is the only thing to show.
  const roster = doc.loaded ? doc.users : sessionDetail?.users ?? [];
  const thread = doc.loaded ? doc.comments : sessionDetail?.comments ?? [];
  const self = joinUid || "console";

  useEffect(() => setDraft(null), [liveSessionId]);

  const [commentLine, setCommentLine] = useState("0");
  const [commentText, setCommentText] = useState("");

  const reportCursor = () => {
    const editor = editorRef.current;
    if (!editor) return;
    // The caret the DOM reports is a UTF-16 offset; the gateway counts code points.
    const pos = offsetToPos(editor.value, unitsToPoints(editor.value, editor.selectionStart));
    setCommentLine(String(pos.line));
    sendCursor(pos.line, pos.col);
  };

  const publishDraft = () => {
    publish(shown);
    reportCursor();
  };

  const createSession = useMutation({
    mutationFn: () => api.collabCreateSession(sessionId, filePath),
    onSuccess: (r) => {
      setMsg(`Session '${r.session_id}' created`);
      setSessionId(""); setFilePath("");
      qc.invalidateQueries({ queryKey: ["collabSessions"] });
    },
    onError: (e) => setError(errorMessage(e, "Create failed")),
  });

  const joinSession = useMutation({
    mutationFn: () => api.collabJoin(joinSid, joinUid, joinName),
    onSuccess: () => {
      setMsg(`Joined session '${joinSid}'`);
      qc.invalidateQueries({ queryKey: ["collabSessions"] });
    },
    onError: (e) => setError(errorMessage(e, "Join failed")),
  });

  // The live tab joins the session it is already showing: `users` is filled by this call, so without
  // it a reader watching a session never appears in it.
  const joinLive = useMutation({
    mutationFn: () => api.collabJoin(selectedSession!.session_id, joinUid, joinName || joinUid),
    onSuccess: () => setMsg(`Joined '${selectedSession?.session_id}' as '${joinUid}'`),
    onError: (e) => setError(errorMessage(e, "Join failed")),
  });

  const leaveLive = useMutation({
    mutationFn: () => api.collabLeave(selectedSession!.session_id, joinUid),
    onSuccess: () => setMsg(`Left '${selectedSession?.session_id}'`),
    onError: (e) => setError(errorMessage(e, "Leave failed")),
  });

  const addComment = useMutation({
    mutationFn: () =>
      api.collabAddComment(selectedSession!.session_id, self, liveFile, Number(commentLine), commentText),
    onSuccess: () => setCommentText(""),
    onError: (e) => setError(errorMessage(e, "Comment failed")),
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
                    <span className="text-xs text-tertiary">{s.connected_users}/{s.users} users v{s.version}</span>
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
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold">Document</h2>
              <span className="text-xs text-tertiary">
                {connected ? "live" : "offline"} · v{doc.loaded ? doc.version : sessionDetail?.version ?? selectedSession.version}
                {dirty && " · unpublished edit"}
              </span>
            </div>
            {doc.error && (
              <div className="p-3 mb-3 rounded-lg text-sm bg-danger-muted text-danger" role="alert">{doc.error}</div>
            )}
            <label htmlFor="collab-editor" className="block text-sm mb-2 text-tertiary">
              {liveFile || "the session document"}
            </label>
            <textarea
              id="collab-editor"
              ref={editorRef}
              value={shown}
              onChange={(e) => setDraft(e.target.value)}
              onKeyUp={reportCursor}
              onClick={reportCursor}
              spellCheck={false}
              className="input-base font-mono text-xs overflow-auto"
              rows={16}
            />
            <div className="flex gap-2 mt-3 flex-wrap">
              <button onClick={publishDraft} disabled={!dirty || !connected || !doc.loaded} className="btn-primary">
                {doc.sent ? "Publishing..." : "Publish edit"}
              </button>
              <button
                onClick={() => joinLive.mutate()}
                disabled={joinLive.isPending || !joinUid}
                className="btn-outline disabled:opacity-40"
              >
                Join as {joinUid || "someone"}
              </button>
              <button
                onClick={() => leaveLive.mutate()}
                disabled={leaveLive.isPending || !joinUid}
                className="btn-outline disabled:opacity-40"
              >
                Leave
              </button>
            </div>
            <p className="text-xs text-tertiary mt-2">
              Publish sends only the difference since the last document this page saw from the gateway. If
              the gateway has moved on, this editor reloads its copy instead of applying an edit it cannot
              account for.
            </p>
          </div>
          <div className="space-y-4">
            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Users ({roster.length})</h2>
              {roster.length === 0 && <p className="text-sm text-tertiary">No one has joined yet.</p>}
              {roster.map((u) => {
                const cursor = doc.cursors[u.id];
                return (
                  <div key={u.id} className="p-2 rounded-lg text-sm mb-1 bg-tertiary">
                    {u.name} ({u.id})
                    {cursor && <span className="ml-2 text-xs text-tertiary">L{cursor.line}:{cursor.column}</span>}
                  </div>
                );
              })}
            </div>
            <div className="card p-4">
              <h2 className="text-lg font-semibold mb-3">Comments ({thread.length})</h2>
              {thread.length === 0 && <p className="text-sm text-tertiary">No comments.</p>}
              {thread.map((c) => (
                <div key={c.id} className="p-2 rounded-lg text-sm mb-1 bg-tertiary">
                  <span className="font-medium">{c.user_id}</span> L{c.line}: {c.text}
                  <span className="ml-2 text-xs">{c.resolved ? "resolved" : "open"}</span>
                </div>
              ))}
              <div className="flex gap-2 mt-3">
                <label htmlFor="collab-comment-line" className="sr-only">Line</label>
                <input
                  id="collab-comment-line"
                  value={commentLine}
                  onChange={(e) => setCommentLine(e.target.value)}
                  className="input-base w-20"
                  inputMode="numeric"
                  aria-label="Line to comment on"
                />
                <input
                  value={commentText}
                  onChange={(e) => setCommentText(e.target.value)}
                  placeholder="Comment"
                  className="input-base flex-1"
                  aria-label="Comment text"
                />
                <button
                  onClick={() => addComment.mutate()}
                  disabled={addComment.isPending || !commentText || !/^\d+$/.test(commentLine)}
                  className="btn-outline disabled:opacity-40"
                >
                  Comment
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
