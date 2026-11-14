/**
 * The document geometry and frame protocol of a collaborative session, in TypeScript.
 *
 * `raven/unique/collaboration.py` applies the same geometry in Python and `raven/core/collab_api.py`
 * emits the frames parsed here. Both sides must resolve a line/column range identically or the editor
 * and the gateway drift apart on the first multi-line edit, so
 * `tests/fixtures/collab_change_cases.json` is one shared table both suites assert against.
 */

export interface CollabUser {
  id: string;
  name: string;
}

export interface CollabChange {
  user_id: string;
  file: string;
  start_line: number;
  start_col: number;
  end_line: number;
  end_col: number;
  old_text: string;
  new_text: string;
}

export interface CollabCursor {
  user_id: string;
  file: string;
  line: number;
  column: number;
}

export interface CollabComment {
  id: string;
  user_id: string;
  file: string;
  line: number;
  text: string;
  resolved: boolean;
}

export type CollabFrame =
  | {
      kind: "state";
      content: string;
      version: number;
      users: CollabUser[];
      comments?: CollabComment[];
      cursors?: CollabCursor[];
    }
  | ({ kind: "change"; version: number } & CollabChange)
  | { kind: "ack"; version: number }
  | { kind: "cursor"; user_id: string; file: string; line: number; column: number }
  | { kind: "user_connected"; user_id: string; session_id: string; user_name?: string }
  | { kind: "user_disconnected"; user_id: string; session_id: string }
  | ({ kind: "comment_added" } & CollabComment)
  | { kind: "error"; content: string }
  | { kind: "pong" };

const VALID_KINDS = new Set([
  "state",
  "change",
  "ack",
  "cursor",
  "user_connected",
  "user_disconnected",
  "comment_added",
  "error",
  "pong",
]);

/**
 * Line/column to an offset into the document, counting each newline as one position.
 *
 * Positions count code points, not UTF-16 units, because that is what a Python `str` indexes and the
 * gateway computes these offsets in Python. An editor that counted units would cut an astral
 * character in half and land every later edit on the wrong column. `lines` comes from
 * `content.split("\n")`; a newline is never part of a surrogate pair, so splitting by unit and
 * counting by point agree on where the lines start.
 */
export function posToOffset(lines: string[], line: number, col: number): number {
  let offset = 0;
  for (let i = 0; i < line; i++) offset += Array.from(lines[i]).length + 1;
  return offset + col;
}

/** The inverse of `posToOffset`, for turning a text diff into a change range. */
export function offsetToPos(content: string, offset: number): { line: number; col: number } {
  const points = Array.from(content);
  const clamped = Math.max(0, Math.min(offset, points.length));
  let line = 0;
  let lineStart = 0;
  for (let i = 0; i < clamped; i++) {
    if (points[i] === "\n") {
      line++;
      lineStart = i + 1;
    }
  }
  return { line, col: clamped - lineStart };
}

/**
 * A DOM offset, in code points.
 *
 * `HTMLTextAreaElement.selectionStart` counts UTF-16 units while the gateway counts code points, so
 * a caret after an emoji is one unit further along than the column the server would report.
 */
export function unitsToPoints(text: string, unitOffset: number): number {
  return Array.from(text.slice(0, Math.max(0, Math.min(unitOffset, text.length)))).length;
}

/**
 * Apply one change, or return null when the document does not contain that range.
 *
 * A refused change leaves the gateway's document untouched and answers the sender with an `error`
 * frame, so null here means "the server would not have applied this either" -- not "ignore it".
 */
export function applyChange(content: string, change: CollabChange): string | null {
  const lines = content.split("\n");
  if (!Number.isInteger(change.start_line) || !Number.isInteger(change.end_line)) return null;
  if (change.start_line < 0 || change.start_line >= lines.length) return null;
  if (change.end_line < 0 || change.end_line >= lines.length) return null;
  const start = posToOffset(lines, change.start_line, change.start_col);
  const end = posToOffset(lines, change.end_line, change.end_col);
  if (end < start) return null;
  const points = Array.from(content);
  return points.slice(0, start).join("") + change.new_text + points.slice(end).join("");
}

/**
 * The smallest single range that turns `prev` into `next`, or null when they are equal.
 *
 * A textarea hands over whole documents; the gateway wants a range. Trimming the shared prefix and
 * suffix keeps the range minimal, so the same keystroke from two clients lands on the same offsets.
 */
export function editToChange(prev: string, next: string, file: string, userId: string): CollabChange | null {
  if (prev === next) return null;
  const before = Array.from(prev);
  const after = Array.from(next);
  let start = 0;
  const shared = Math.min(before.length, after.length);
  while (start < shared && before[start] === after[start]) start++;
  let prevEnd = before.length;
  let nextEnd = after.length;
  while (prevEnd > start && nextEnd > start && before[prevEnd - 1] === after[nextEnd - 1]) {
    prevEnd--;
    nextEnd--;
  }
  const from = offsetToPos(prev, start);
  const to = offsetToPos(prev, prevEnd);
  return {
    user_id: userId,
    file,
    start_line: from.line,
    start_col: from.col,
    end_line: to.line,
    end_col: to.col,
    old_text: before.slice(start, prevEnd).join(""),
    new_text: after.slice(start, nextEnd).join(""),
  };
}

export interface CollabDoc {
  content: string;
  version: number;
  users: CollabUser[];
  comments: CollabComment[];
  cursors: Record<string, CollabCursor>;
  /** A `state` frame has arrived, so this document is the gateway's, not a REST snapshot. */
  loaded: boolean;
  /** The edit this client has published and not yet had confirmed. */
  sent: { change: CollabChange; content: string } | null;
  /** The gateway's document no longer matches what this client can reconstruct. */
  resync: boolean;
  error: string;
}

export function emptyDoc(): CollabDoc {
  return {
    content: "",
    version: 0,
    users: [],
    comments: [],
    cursors: {},
    loaded: false,
    sent: null,
    resync: false,
    error: "",
  };
}

/** Hold the optimistic document until the gateway confirms the edit. */
export function withSentChange(doc: CollabDoc, change: CollabChange): CollabDoc {
  const applied = applyChange(doc.content, change);
  if (applied === null) return { ...doc, error: "This edit does not apply to the current document." };
  return { ...doc, sent: { change, content: applied } };
}

/**
 * Fold one gateway frame into the document.
 *
 * Every branch that cannot be reconciled sets `resync` instead of guessing: a client that quietly
 * applied a change it had not seen would show a document the gateway does not have.
 */
export function handleFrame(doc: CollabDoc, frame: CollabFrame): CollabDoc {
  switch (frame.kind) {
    case "state":
      return {
        ...doc,
        content: frame.content,
        version: frame.version,
        users: frame.users,
        comments: frame.comments ?? [],
        cursors: indexCursors(frame.cursors ?? []),
        loaded: true,
        sent: null,
        resync: false,
        error: "",
      };
    case "change": {
      if (frame.version !== doc.version + 1) return { ...doc, resync: true };
      const applied = applyChange(doc.content, frame);
      if (applied === null) return { ...doc, resync: true };
      return { ...doc, content: applied, version: frame.version };
    }
    case "ack": {
      if (!doc.sent) return { ...doc, version: frame.version };
      if (frame.version !== doc.version + 1) return { ...doc, sent: null, resync: true };
      return { ...doc, content: doc.sent.content, version: frame.version, sent: null };
    }
    case "cursor":
      return { ...doc, cursors: { ...doc.cursors, [frame.user_id]: { ...frame } } };
    case "user_connected": {
      if (doc.users.some((u) => u.id === frame.user_id)) return doc;
      // A socket join carries no display name: all the gateway knows is what the token resolves to.
      return { ...doc, users: [...doc.users, { id: frame.user_id, name: frame.user_name ?? frame.user_id }] };
    }
    case "user_disconnected":
      return {
        ...doc,
        users: doc.users.filter((u) => u.id !== frame.user_id),
        cursors: withoutKey(doc.cursors, frame.user_id),
      };
    case "comment_added": {
      if (doc.comments.some((c) => c.id === frame.id)) return doc;
      return {
        ...doc,
        comments: [
          ...doc.comments,
          { id: frame.id, user_id: frame.user_id, file: frame.file, line: frame.line, text: frame.text, resolved: frame.resolved },
        ],
      };
    }
    case "error":
      return { ...doc, sent: null, error: frame.content };
    case "pong":
      return doc;
  }
}

function indexCursors(cursors: CollabCursor[]): Record<string, CollabCursor> {
  const byUser: Record<string, CollabCursor> = {};
  for (const cursor of cursors) byUser[cursor.user_id] = cursor;
  return byUser;
}

function withoutKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next: Record<string, T> = {};
  for (const [name, value] of Object.entries(record)) if (name !== key) next[name] = value;
  return next;
}

/** Parse a socket payload into a frame, or null when it is not a frame this protocol knows. */
export function parseFrame(raw: string): CollabFrame | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const frame = data as Record<string, unknown>;
  const kind = frame.kind;
  if (typeof kind !== "string" || !VALID_KINDS.has(kind)) return null;
  // A frame missing the fields the reducer branches on would move the document to an unknown point,
  // so they are checked here rather than trusted.
  if ((kind === "state" || kind === "change" || kind === "ack") && typeof frame.version !== "number") return null;
  if (kind === "state" && (typeof frame.content !== "string" || !Array.isArray(frame.users))) return null;
  if (kind === "error" && typeof frame.content !== "string") return null;
  if (kind === "change") {
    if (typeof frame.new_text !== "string") return null;
    if (!["start_line", "start_col", "end_line", "end_col"].every((key) => typeof frame[key] === "number")) return null;
  }
  if (kind === "cursor") {
    if (typeof frame.user_id !== "string") return null;
    if (typeof frame.line !== "number" || typeof frame.column !== "number") return null;
  }
  if ((kind === "user_connected" || kind === "user_disconnected" || kind === "comment_added") && typeof frame.user_id !== "string") {
    return null;
  }
  if (kind === "comment_added") {
    if (typeof frame.id !== "string" || typeof frame.text !== "string") return null;
    if (typeof frame.line !== "number" || typeof frame.resolved !== "boolean") return null;
  }
  return data as CollabFrame;
}
