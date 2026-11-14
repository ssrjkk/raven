import { describe, expect, it } from "vitest";

import rawTable from "../../../tests/fixtures/collab_change_cases.json";
import {
  applyChange,
  type CollabChange,
  type CollabDoc,
  type CollabFrame,
  editToChange,
  emptyDoc,
  handleFrame,
  offsetToPos,
  parseFrame,
  posToOffset,
  unitsToPoints,
  withSentChange,
} from "./collab";

interface CaseRow {
  name: string;
  content: string;
  change: CollabChange;
  applies: boolean;
  expected: string;
}

interface RoundtripRow {
  name: string;
  prev: string;
  change: CollabChange;
  next: string;
}

/**
 * The same table `tests/test_collab_change_parity.py` asserts in Python.
 *
 * Its rows are produced by the gateway's own `CollaborationSession.apply_change`, so a failure here
 * means this client would show a document the server does not have -- not a guess about the server.
 */
const table = rawTable as unknown as { cases: CaseRow[]; roundtrip: RoundtripRow[] };

function doc(partial: Partial<CollabDoc> = {}): CollabDoc {
  return { ...emptyDoc(), ...partial };
}

function changeFrame(partial: Partial<CollabChange> & { version: number }): CollabFrame {
  return {
    kind: "change",
    user_id: "u",
    file: "f.py",
    start_line: 0,
    start_col: 0,
    end_line: 0,
    end_col: 0,
    old_text: "",
    new_text: "",
    ...partial,
  };
}

describe("collab geometry against the shared table", () => {
  it.each(table.cases)("$name", (row) => {
    const applied = applyChange(row.content, row.change);
    if (row.applies) expect(applied).toBe(row.expected);
    else expect(applied).toBeNull();
  });

  it.each(table.roundtrip)("$name round-trips", (row) => {
    expect(applyChange(row.prev, row.change)).toBe(row.next);
    expect(editToChange(row.prev, row.next, row.change.file, row.change.user_id)).toEqual(row.change);
  });

  it("proves the table still carries the cases that used to diverge", () => {
    expect(table.cases.length).toBeGreaterThan(0);
    expect(table.roundtrip.length).toBeGreaterThan(0);
    expect(table.cases.some((row) => !row.applies)).toBe(true);
    expect(table.cases.some((row) => row.change.end_line > row.change.start_line && row.applies)).toBe(true);
    expect(table.roundtrip.some((row) => /[а-яА-ЯёЁ]/.test(row.next))).toBe(true);
    // Astral characters are where a code-unit client and a code-point server part company.
    expect(table.roundtrip.some((row) => [...row.next].some((point) => (point.codePointAt(0) ?? 0) > 0xffff)))
      .toBe(true);
  });
});

describe("offsets", () => {
  it("counts code points, the way the gateway counts them", () => {
    // Four is what a UTF-16 client would say: the emoji is two units there, one character in Python.
    expect(posToOffset(["😀a", "bc"], 1, 0)).toBe(3);
    expect(applyChange("😀\nabc", {
      user_id: "u",
      file: "f.py",
      start_line: 1,
      start_col: 1,
      end_line: 1,
      end_col: 2,
      old_text: "b",
      new_text: "X",
    })).toBe("😀\naXc");
    expect(applyChange("a😀b", {
      user_id: "u",
      file: "f.py",
      start_line: 0,
      start_col: 1,
      end_line: 0,
      end_col: 2,
      old_text: "😀",
      new_text: "",
    })).toBe("ab");
  });

  it("inverts itself across a multi-line document", () => {
    const content = "😀first\nsecond\nthird";
    const points = Array.from(content);
    const lines = content.split("\n");
    points.forEach((_, offset) => {
      const { line, col } = offsetToPos(content, offset);
      expect(posToOffset(lines, line, col)).toBe(offset);
    });
    expect(offsetToPos(content, -5)).toEqual({ line: 0, col: 0 });
    expect(offsetToPos(content, points.length + 5)).toEqual({ line: 2, col: 5 });
  });

  it("turns a caret reported in UTF-16 units into a code-point offset", () => {
    const value = "😀ab";
    expect(unitsToPoints(value, value.indexOf("a"))).toBe(1);
    expect(unitsToPoints(value, value.length)).toBe(3);
    expect(unitsToPoints(value, -1)).toBe(0);
  });
});

describe("editToChange", () => {
  it("is null when nothing changed", () => {
    expect(editToChange("same", "same", "f.py", "u")).toBeNull();
  });

  it("keeps the range minimal when the suffix repeats", () => {
    const change = editToChange("abc", "abcabc", "f.py", "u");
    expect(change).not.toBeNull();
    expect(change!.old_text).toBe("");
    expect(change!.new_text).toBe("abc");
    expect(change!.end_col).toBe(3);
  });

  it("refuses to hold an edit for a line the document does not have", () => {
    const next = withSentChange(doc({ content: "abc" }), {
      user_id: "u",
      file: "f.py",
      start_line: 4,
      start_col: 0,
      end_line: 4,
      end_col: 0,
      old_text: "",
      new_text: "x",
    });
    expect(next.sent).toBeNull();
    expect(next.error).toContain("does not apply");
  });

  it("holds a column past the line end, because the gateway clamps it the same way", () => {
    const next = withSentChange(doc({ content: "abc" }), {
      user_id: "u",
      file: "f.py",
      start_line: 0,
      start_col: 0,
      end_line: 0,
      end_col: 9,
      old_text: "",
      new_text: "x",
    });
    expect(next.sent?.content).toBe("x");
  });
});

describe("handleFrame", () => {
  it("takes a state frame as the authoritative document", () => {
    const next = handleFrame(
      doc({ content: "stale", version: 9, sent: { change: {} as CollabChange, content: "optimistic" }, resync: true, error: "boom" }),
      {
        kind: "state",
        content: "the gateway's text",
        version: 4,
        users: [{ id: "u1", name: "Ada" }],
        comments: [{ id: "c1", user_id: "u1", file: "f.py", line: 2, text: "why", resolved: false }],
        cursors: [{ user_id: "u1", file: "f.py", line: 1, column: 3 }],
      },
    );
    expect(next).toMatchObject({ content: "the gateway's text", version: 4, loaded: true, sent: null, resync: false, error: "" });
    expect(next.comments).toHaveLength(1);
    expect(next.cursors.u1).toMatchObject({ line: 1, column: 3 });
  });

  it("applies the next change and asks for a resync for anything else", () => {
    const base = doc({ content: "abc", version: 1, loaded: true });
    const applied = handleFrame(base, changeFrame({ version: 2, start_col: 0, end_col: 1, old_text: "a", new_text: "z" }));
    expect(applied).toMatchObject({ content: "zbc", version: 2, resync: false });

    const early = handleFrame(base, changeFrame({ version: 5, start_col: 0, end_col: 1, old_text: "a", new_text: "z" }));
    expect(early.resync).toBe(true);

    const impossible = handleFrame(base, changeFrame({ version: 2, start_line: 7, end_line: 7 }));
    expect(impossible.resync).toBe(true);
  });

  it("adopts the optimistic edit only on the acknowledgement it belongs to", () => {
    const sent = withSentChange(doc({ content: "abc", version: 1, loaded: true }), {
      user_id: "u",
      file: "f.py",
      start_line: 0,
      start_col: 0,
      end_line: 0,
      end_col: 0,
      old_text: "",
      new_text: ">> ",
    });
    expect(sent).toMatchObject({ content: "abc", version: 1 });

    expect(handleFrame(sent, { kind: "ack", version: 2 })).toMatchObject({
      content: ">> abc",
      version: 2,
      sent: null,
      resync: false,
    });
    expect(handleFrame(sent, { kind: "ack", version: 7 })).toMatchObject({ sent: null, resync: true });
    expect(handleFrame(doc({ content: "abc", version: 1 }), { kind: "ack", version: 2 })).toMatchObject({
      content: "abc",
      version: 2,
      resync: false,
    });
  });

  it("keeps presence in step with the gateway", () => {
    const joined = handleFrame(doc({ users: [{ id: "u1", name: "Ada" }] }),
      { kind: "user_connected", user_id: "u2", session_id: "s", user_name: "Bob" });
    expect(joined.users).toEqual([{ id: "u1", name: "Ada" }, { id: "u2", name: "Bob" }]);

    // A socket join carries no display name, so the id is all there is to show.
    expect(handleFrame(doc(), { kind: "user_connected", user_id: "u3", session_id: "s" }).users).toEqual([
      { id: "u3", name: "u3" },
    ]);
    expect(handleFrame(joined, { kind: "user_connected", user_id: "u2", session_id: "s" }).users).toHaveLength(2);

    const withCursor = handleFrame(doc({ users: [{ id: "u2", name: "Bob" }] }),
      { kind: "cursor", user_id: "u2", file: "f.py", line: 3, column: 1 });
    expect(withCursor.cursors.u2).toMatchObject({ line: 3, column: 1 });

    const left = handleFrame(withCursor, { kind: "user_disconnected", user_id: "u2", session_id: "s" });
    expect(left.users).toEqual([]);
    expect(left.cursors).toEqual({});
  });

  it("adds a comment once", () => {
    const comment: CollabFrame = { kind: "comment_added", id: "c1", user_id: "u1", file: "f.py", line: 0, text: "hi", resolved: false };
    const once = handleFrame(doc(), comment);
    expect(once.comments).toHaveLength(1);
    expect(handleFrame(once, comment).comments).toHaveLength(1);
  });

  it("reports a refusal without losing the document", () => {
    const next = handleFrame(
      doc({ content: "keep", version: 3, sent: { change: {} as CollabChange, content: "gone" } }),
      { kind: "error", content: "Change could not be applied" },
    );
    expect(next).toMatchObject({ content: "keep", version: 3, sent: null, error: "Change could not be applied" });
  });

  it("ignores a pong", () => {
    const base = doc({ content: "abc" });
    expect(handleFrame(base, { kind: "pong" })).toBe(base);
  });
});

describe("parseFrame", () => {
  it("accepts every kind the gateway emits", () => {
    const payloads: unknown[] = [
      { kind: "state", content: "", version: 0, users: [] },
      { kind: "change", version: 1, user_id: "u", file: "f", start_line: 0, start_col: 0, end_line: 0, end_col: 0,
        old_text: "", new_text: "x" },
      { kind: "ack", version: 1 },
      { kind: "cursor", user_id: "u", file: "f", line: 0, column: 0 },
      { kind: "user_connected", user_id: "u", session_id: "s" },
      { kind: "user_disconnected", user_id: "u", session_id: "s" },
      { kind: "comment_added", id: "c", user_id: "u", file: "f", line: 0, text: "t", resolved: false },
      { kind: "error", content: "no" },
      { kind: "pong" },
    ];
    for (const payload of payloads) {
      expect(parseFrame(JSON.stringify(payload))).toEqual(payload);
    }
  });

  it("rejects anything that is not a frame", () => {
    expect(parseFrame("not json")).toBeNull();
    expect(parseFrame('"a string"')).toBeNull();
    expect(parseFrame("null")).toBeNull();
    expect(parseFrame("[]")).toBeNull();
    expect(parseFrame("{}")).toBeNull();
    expect(parseFrame(JSON.stringify({ kind: "typo", version: 1 }))).toBeNull();
  });

  it("rejects frames missing the fields the reducer branches on", () => {
    const payloads: unknown[] = [
      { kind: "state", content: "" },
      { kind: "state", content: 5, version: 1, users: [] },
      { kind: "state", content: "", version: 1, users: "Ada" },
      { kind: "ack" },
      { kind: "change", version: 1, user_id: "u", file: "f", start_line: 0, start_col: 0, end_line: 0, end_col: 0,
        old_text: "" },
      { kind: "change", version: 1, new_text: "x", start_line: 0, start_col: 0, end_line: 0 },
      { kind: "cursor", user_id: "u", file: "f", line: 0 },
      { kind: "user_connected", session_id: "s" },
      { kind: "comment_added", id: "c", user_id: "u", file: "f", line: 0, text: "t" },
      { kind: "comment_added", id: "c", user_id: "u", file: "f", line: "0", text: "t", resolved: false },
      { kind: "error" },
    ];
    for (const payload of payloads) {
      expect(parseFrame(JSON.stringify(payload))).toBeNull();
    }
  });
});
