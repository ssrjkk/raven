"""One contract for the collab socket: what the gateway puts on the wire is what the console parses.

The console ignored `/api/collab/sessions/{id}/ws` until wave #130e, so nothing on either side was
checked against the other. A gateway frame the browser does not know how to read is a silent no-op,
and a kind the browser parses but the gateway never sends is a branch nobody can ever reach. Both
are invisible to a test that only exercises one side, so this module compares the two.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
from collections.abc import Iterator
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from raven.core import collab_api
from raven.core.collab_api import create_collab_router
from raven.core.config import settings
from raven.unique.collaboration import CollaborationManager, WebSocketManager

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT_LIB = ROOT / "web" / "src" / "lib" / "collab.ts"
CLIENT_HOOK = ROOT / "web" / "src" / "hooks" / "useCollabSocket.ts"
SERVER_SOURCES = (ROOT / "raven" / "core" / "collab_api.py", ROOT / "raven" / "unique" / "collaboration.py")

TOKEN = "operator-key-under-test"
SESSION = "parity-1"
WAIT_SECONDS = 5.0

CHANGE = {
    "kind": "change",
    "file": "a.py",
    "start_line": 0,
    "start_col": 0,
    "end_line": 0,
    "end_col": 0,
    "old_text": "",
    "new_text": "alpha",
}


def _server_trees() -> list[ast.Module]:
    return [ast.parse(path.read_text(encoding="utf-8")) for path in SERVER_SOURCES]


def _kind_values(node: ast.Dict) -> list[ast.expr]:
    """The value expressions assigned to a `kind` key of a dict literal."""
    return [
        value
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "kind"
    ]


def _server_emits_kinds() -> set[str]:
    """Every frame kind the gateway can put on the wire, read off the source.

    A kind is either a string literal in a frame dict or a frame builder that takes the kind as an
    argument -- `_presence_frame(kind, ...)` -- in which case the literals are at its call sites.
    Reading only the literals would miss the presence frames, which is the whole announcement channel.
    """
    trees = _server_trees()
    found: set[str] = set()
    parameterized: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Dict):
                    continue
                for value in _kind_values(sub):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        found.add(value.value)
                    elif isinstance(value, ast.Name):
                        parameterized.add(node.name)
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in parameterized or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def _client_parsed_kinds() -> set[str]:
    """The `VALID_KINDS` set the console's frame parser accepts."""
    source = CLIENT_LIB.read_text(encoding="utf-8")
    block = re.search(r"const VALID_KINDS = new Set\(\[(.*?)\]\);", source, re.S)
    assert block is not None, "the console must list the frame kinds it accepts in one set"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def _client_declared_kinds() -> set[str]:
    """The `kind` literals of the `CollabFrame` union -- what the reducers are typed to receive."""
    source = CLIENT_LIB.read_text(encoding="utf-8")
    start = source.find("export type CollabFrame")
    stop = source.find("const VALID_KINDS", start)
    assert start != -1 and stop != -1, "the console must declare one CollabFrame union above its parse set"
    return set(re.findall(r'kind:\s*"([a-z_]+)"', source[start:stop]))


def _client_sends_kinds() -> set[str]:
    """The kinds the console writes to the socket."""
    source = CLIENT_HOOK.read_text(encoding="utf-8")
    return set(re.findall(r'JSON\.stringify\(\{\s*kind:\s*"([a-z_]+)"', source))


def _server_handles_kinds() -> set[str]:
    """The kinds the websocket handler branches on for inbound frames."""
    tree = ast.parse((ROOT / "raven" / "core" / "collab_api.py").read_text(encoding="utf-8"))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "collab_websocket"
    ]
    assert handlers, "the collab router must define a collab_websocket handler"
    found: set[str] = set()
    for node in ast.walk(handlers[0]):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name) or node.left.id != "kind":
            continue
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                found.add(comparator.value)
    return found


def test_the_gateway_emits_exactly_the_kinds_the_console_parses() -> None:
    assert _server_emits_kinds() == _client_parsed_kinds()


def test_the_console_parses_exactly_the_kinds_its_frame_type_declares() -> None:
    """A kind in the union but not in the parse set can never arrive; one in the parse set but not the
    union reaches the reducer untyped."""
    assert _client_declared_kinds() == _client_parsed_kinds()


def test_every_kind_the_console_sends_is_branchable_by_the_handler() -> None:
    """An unbranched inbound kind falls through to `Unknown frame kind`, so the editor's own edits and
    cursors would never take effect while every test of the socket still passed."""
    unhandled = sorted(_client_sends_kinds() - _server_handles_kinds())
    assert not unhandled, f"the handler has no branch for {unhandled}"


class TestFramesOnTheWire:
    """The same comparison driven for real, so a kind neither side can reach fails here even when the
    two static sets agree.

    A mocked manager answers whatever frame shape the test asks for, which is exactly the claim under
    test; everything below runs the real stores over `TestClient`.
    """

    @pytest.fixture()
    def live(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        monkeypatch.setattr(collab_api, "_manager", CollaborationManager())
        monkeypatch.setattr(collab_api, "_ws_manager", WebSocketManager())
        monkeypatch.setattr(settings, "web_secret_key", SecretStr(TOKEN))
        app = FastAPI()
        app.include_router(create_collab_router())
        with TestClient(app) as client:
            client.post("/api/collab/sessions", json={"session_id": SESSION, "file_path": "a.py"})
            yield client

    @staticmethod
    def _socket(client: TestClient) -> Any:
        return client.websocket_connect(f"/api/collab/sessions/{SESSION}/ws?token={TOKEN}")

    @staticmethod
    def _next_frame(ws: Any) -> dict[str, Any] | None:
        """One frame, or None when nothing arrives.

        `TestClient`'s own receive parks forever on a frame that never comes, so a gateway that
        stopped sending one would hang the gate instead of failing it. The stream a test session
        reads from is Starlette internals, but it is the only place the wait can be bounded.
        """

        async def poll() -> Any:
            with anyio.move_on_after(WAIT_SECONDS):
                return await ws._send_rx.receive()
            return None

        message = ws.portal.call(poll)
        if message is None:
            return None
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(code=int(message.get("code", 1000)), reason=str(message.get("reason", "")))
        frame: dict[str, Any] = json.loads(str(message["text"]))
        return frame

    @classmethod
    def _until(cls, ws: Any, kind: str, seen: set[str]) -> dict[str, Any]:
        """Read frames until `kind` arrives, recording every kind that actually did."""
        for _ in range(8):
            frame = cls._next_frame(ws)
            if frame is None:
                pytest.fail(f"no {kind!r} frame; this socket had already received {sorted(seen)}")
            seen.add(str(frame.get("kind")))
            if frame.get("kind") == kind:
                return frame
        pytest.fail(f"no {kind!r} frame in the first 8 frames")

    def test_every_kind_the_gateway_is_written_to_send_reaches_the_socket(self, live: TestClient) -> None:
        seen: set[str] = set()
        with self._socket(live) as first, self._socket(live) as second:
            self._until(first, "state", seen)
            self._until(second, "state", seen)
            self._until(first, "user_connected", seen)

            first.send_json(CHANGE)
            self._until(first, "ack", seen)
            self._until(second, "change", seen)

            first.send_json({"kind": "cursor", "file": "a.py", "line": 0, "column": 3})
            self._until(second, "cursor", seen)

            first.send_json({"kind": "ping"})
            self._until(first, "pong", seen)

            live.post(
                f"/api/collab/sessions/{SESSION}/comments",
                json={"session_id": SESSION, "user_id": "u9", "file": "a.py", "line": 0, "text": "why"},
            )
            self._until(second, "comment_added", seen)

            live.post(
                f"/api/collab/sessions/{SESSION}/join",
                json={"session_id": SESSION, "user_id": "u9", "user_name": "Nina"},
            )
            self._until(second, "user_connected", seen)
            live.post(
                f"/api/collab/sessions/{SESSION}/leave",
                json={"session_id": SESSION, "user_id": "u9"},
            )
            self._until(second, "user_disconnected", seen)

            first.send_json({"kind": "typing"})
            self._until(first, "error", seen)

        assert seen == _client_parsed_kinds()

    def test_a_frame_meant_for_the_document_carries_the_fields_the_reducer_needs(self, live: TestClient) -> None:
        """The parse gate drops a frame whose version is missing, and the reducer splices a change by
        its range; a broadcast that satisfies neither reads as a socket that simply stopped."""
        with self._socket(live) as first, self._socket(live) as second:
            self._until(first, "state", set())
            self._until(second, "state", set())
            first.send_json(CHANGE)
            frame = self._until(second, "change", set())
        for field in ("version", "start_line", "start_col", "end_line", "end_col", "old_text", "new_text", "file"):
            assert field in frame, f"the change frame dropped {field!r}"
