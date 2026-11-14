import { useCallback, useEffect, useRef, useState } from "react";

import { api, getToken } from "../api/client";
import {
  CollabDoc,
  CollabFrame,
  editToChange,
  emptyDoc,
  handleFrame,
  parseFrame,
  withSentChange,
} from "../lib/collab";
import { computeReconnectDelay } from "./useWebSocket";

export interface CollabSocketState {
  doc: CollabDoc;
  connected: boolean;
  /** Publish the whole editor buffer as the smallest change that turns the gateway's document into it. */
  publish: (next: string) => void;
  sendCursor: (line: number, column: number) => void;
}

/**
 * Live document socket for one collaboration session.
 *
 * The gateway speaks `/api/collab/sessions/{id}/ws`: it authenticates from `?token=`, answers a new
 * socket with a `state` frame, then broadcasts `change`, `cursor` and presence frames to everyone
 * else. Nothing in the console connected to it before this hook existed, so Session Details rendered
 * a snapshot that only a reload could refresh while the document changed underneath it.
 */
export function useCollabSocket(sessionId: string | null, file: string): CollabSocketState {
  const [doc, setDoc] = useState<CollabDoc>(emptyDoc);
  const [connected, setConnected] = useState(false);
  const docRef = useRef<CollabDoc>(doc);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);

  docRef.current = doc;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const dispatch = useCallback((frame: CollabFrame) => {
    setDoc((current) => handleFrame(current, frame));
  }, []);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
    if (!sessionId) {
      setDoc(emptyDoc());
      return;
    }
    const open = () => {
      if (!mountedRef.current) return;
      const token = getToken();
      if (!token) {
        setDoc((current) => ({ ...current, error: "Sign in to open a live session." }));
        return;
      }
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const url =
        `${protocol}//${location.host}/api/collab/sessions/${encodeURIComponent(sessionId)}/ws` +
        `?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      ws.onopen = () => {
        attemptRef.current = 0;
        setConnected(true);
      };
      ws.onclose = (event) => {
        setConnected(false);
        if (!mountedRef.current) return;
        // 1008 is the gateway saying the credential did not resolve. Retrying it on a timer turns one
        // sign-in problem into an endless reconnect against a socket that will never be accepted.
        if (event.code === 1008) {
          setDoc((current) => ({ ...current, error: "This gateway rejected the session token." }));
          return;
        }
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(open, computeReconnectDelay(attemptRef.current));
        attemptRef.current += 1;
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        const frame = parseFrame(String(event.data));
        if (frame) dispatch(frame);
      };
      wsRef.current = ws;
    };
    open();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [dispatch, sessionId]);

  // The reducer stops merging as soon as it cannot account for a version. The gateway's own document
  // is the only answer, so ask for it rather than keep editing a stale copy.
  useEffect(() => {
    if (!doc.resync || !sessionId) return;
    let stale = false;
    api
      .collabGetContent(sessionId)
      .then((snapshot) => {
        if (stale || !mountedRef.current) return;
        setDoc((current) => ({
          ...current,
          content: snapshot.content,
          version: snapshot.version,
          loaded: true,
          sent: null,
          resync: false,
          error: "",
        }));
      })
      .catch((err: unknown) => {
        if (stale || !mountedRef.current) return;
        setDoc((current) => ({
          ...current,
          resync: false,
          error: `Could not reload the gateway document: ${err instanceof Error ? err.message : String(err)}`,
        }));
      });
    return () => {
      stale = true;
    };
  }, [doc.resync, sessionId]);

  const publish = useCallback(
    (next: string) => {
      const current = docRef.current;
      // A range only means something against the document it was cut from. Before the first `state`
      // frame this client holds a REST snapshot it cannot prove the gateway still has, so the smallest
      // change that turns it into the editor buffer would be an insert spliced in front of the
      // server's copy rather than the edit the operator typed.
      if (!current.loaded) {
        setDoc({ ...current, error: "The gateway has not sent its document yet; this edit was not published." });
        return;
      }
      // The gateway stamps the author from the token and ignores any identity in the payload, so the
      // frame carries an empty one instead of a name this browser made up.
      const change = editToChange(current.content, next, file, "");
      if (!change) return;
      const optimistic = withSentChange(current, change);
      const ws = wsRef.current;
      if (optimistic.sent && (!ws || ws.readyState !== WebSocket.OPEN)) {
        setDoc({ ...optimistic, sent: null, error: "The session socket is offline; this edit was not published." });
        return;
      }
      setDoc(optimistic);
      if (!optimistic.sent || !ws) return;
      ws.send(JSON.stringify({ kind: "change", ...change }));
    },
    [file],
  );

  const sendCursor = useCallback(
    (line: number, column: number) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ kind: "cursor", file, line, column }));
    },
    [file],
  );

  return { doc, connected, publish, sendCursor };
}
