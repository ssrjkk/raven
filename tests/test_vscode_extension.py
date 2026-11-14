"""The VS Code extension against the gateway it ships with.

Measured before this wave: the panel opened `/ws` and sent the user's text as the first frame, which is
the frame `_authenticate_ws` reads as the credential envelope -- so the gateway closed 1008 and the
panel reconnect-looped every three seconds forever; `health()` probed `/health`, a path no server here
answers, and the SPA catch-all returned index.html with a 200, so the status bar reported a connection
to any process on the port; and no request carried a credential at all, while `/api/raven` sits behind
`admin:write`.

The socket and route tests below run against the real apps. The rest read the extension's own source,
because nothing but VS Code executes these files: a check that never touches them would let the
shipped extension regress while the suite stayed green.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from raven.channels.webchat.channel import WebChatChannel
from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.spa import mount_spa
from raven.core.status_api import create_status_router

EXT = pathlib.Path(__file__).resolve().parents[1] / "extension" / "vscode"
REPO = EXT.parent.parent
SOURCES = sorted((EXT / "src").glob("*.ts"))


def _source(name: str) -> str:
    return (EXT / "src" / name).read_text(encoding="utf-8")


def _panel_script() -> str:
    block = re.search(r"<script>([\s\S]*?)</script>", _source("panel.ts"))
    assert block, "the chat panel has no script block"
    return block.group(1)


def _webchat_client() -> TestClient:
    # /ws needs no database: the handler it forwards to belongs to the gateway, and the handshake
    # under test ends before any message is routed.
    return TestClient(WebChatChannel(SimpleNamespace()).app)  # type: ignore[arg-type]


def _operator_token() -> str:
    return settings.web_secret_key.get_secret_value()


# --- the socket handshake, against the server that answers it ---


def test_a_first_frame_that_is_not_the_credential_is_closed() -> None:
    """What the panel used to send: the user's text, where the gateway reads a credential envelope."""
    with pytest.raises(WebSocketDisconnect) as ei:
        with _webchat_client().websocket_connect("/ws") as ws:
            ws.send_json({"text": "hello", "session_id": "vscode:panel:default"})
            ws.receive_json()
    assert ei.value.code == 1008


def test_a_credential_this_install_does_not_know_is_closed() -> None:
    with pytest.raises(WebSocketDisconnect) as ei:
        with _webchat_client().websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "not-a-token"})
            ws.receive_json()
    assert ei.value.code == 1008


def test_the_panel_handshake_opens_the_session_it_asks_about() -> None:
    """`{type: "auth", token}` first, then the gateway names a session back -- the frame pair the panel
    script now sends, in the order it sends them."""
    with _webchat_client().websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": _operator_token()})
        frame = ws.receive_json()
    assert frame["type"] == "session"
    assert frame["session_id"].startswith("webchat:")


def test_a_session_token_opens_the_socket_too() -> None:
    """The panel authenticates with any credential the gateway accepts, not only the operator key."""
    token = asyncio.run(token_manager.create_token("editor-user", "user"))
    with _webchat_client().websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "session"


def test_the_panel_authenticates_before_it_sends_and_echoes_the_servers_session() -> None:
    script = _panel_script()
    assert re.search(r"type:\s*'auth',\s*token", script), "the panel sends no credential frame"
    assert "session_id: sessionId" in script, "the panel does not send on the session it was given"
    assert "'vscode:panel:default'" not in script
    guard = next((line for line in script.splitlines() if line.strip().startswith("if (!text")), "")
    assert "sessionId" in guard, "the panel can send before the session frame lands"


def test_the_panel_never_reports_connected_before_the_gateway_names_a_session() -> None:
    """`onopen` used to set the label, which claimed a working chat while the socket was still
    anonymous and about to be closed."""
    script = _panel_script()
    onopen = next(line for line in script.splitlines() if "ws.onopen" in line)
    assert "setStatus" not in onopen
    assert re.search(r"data\.type === 'session'[\s\S]{0,140}setStatus\('connected'\)", script)


# --- the health probe, against the port the extension points at ---


@pytest.fixture
def gateway_client(tmp_path: pathlib.Path) -> TestClient:
    """The routes a caller of the gateway port reaches, SPA catch-all included."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><title>Raven</title>", encoding="utf-8")
    app = FastAPI()
    app.include_router(create_status_router(SimpleNamespace(), SimpleNamespace(), SimpleNamespace()))  # type: ignore[arg-type]
    assert mount_spa(app, tmp_path)
    return TestClient(app)


def test_the_catch_all_makes_any_unknown_path_look_alive(gateway_client: TestClient) -> None:
    """Why a status code alone cannot carry a health signal on this port."""
    swallowed = gateway_client.get("/health")
    assert swallowed.status_code == 200
    assert "text/html" in swallowed.headers["content-type"]
    live = gateway_client.get("/api/health/live")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}


def test_the_probe_asks_the_liveness_route_and_reads_the_answer() -> None:
    """Asserted on the request line, because the reason `/health` is the wrong path is written in a
    comment directly above it -- a substring test over the file passes while the code still probes a
    file served by the catch-all."""
    api = _source("api.ts")
    body = api[api.index("async health():") :]
    request = next((line for line in body.splitlines() if "fetch(" in line), "")
    assert "/api/health/live" in request, "the probe is on a path the gateway answers with a page"
    assert re.search(r"body\.status === 'ok'", body), "the probe trusts the status line alone"


# --- the credential ---


def test_every_api_call_carries_the_stored_credential() -> None:
    api = _source("api.ts")
    assert "headers.Authorization = `Bearer ${token}`" in api
    assert "this.secrets.get(TOKEN_SECRET)" in api
    assert "headers: await this.headers()" in api


def test_the_token_is_not_stored_in_a_setting() -> None:
    """`"format": "password"` masks the input box and still writes settings.json in plain text."""
    assert '"raven.token"' not in (EXT / "package.json").read_text(encoding="utf-8")
    assert "TOKEN_SECRET" in _source("config.ts")
    assert "secrets.store(TOKEN_SECRET" in _source("extension.ts")


def test_the_socket_credential_reaches_the_webview_without_touching_the_html() -> None:
    """The token is posted to the page after it asks; the rendered document never carries it."""
    panel = _source("panel.ts")
    assert "postMessage({ type: 'gatewayToken'" in panel
    html = panel[panel.index("return `<!DOCTYPE html>") :]
    assert not [i for i in re.findall(r"\$\{[^}]*\}", html) if "token" in i.lower()]


def test_the_extension_reads_its_endpoint_at_call_time() -> None:
    """A setting VS Code applies without a reload has to reach the next request."""
    api = _source("api.ts")
    assert "getConfig().endpoint" in api
    assert not re.search(r"constructor\([^)]*endpoint", api)


# --- the manifest and the code behind it ---


def _command_ids(text: str) -> set[str]:
    return set(re.findall(r"'(raven\.[A-Za-z]+)'", text))


def test_every_command_the_palette_offers_has_a_handler() -> None:
    contributes = json.loads((EXT / "package.json").read_text(encoding="utf-8"))["contributes"]
    declared = {item["command"] for item in contributes["commands"]}
    titles = {item["command"]: item.get("title", "") for item in contributes["commands"]}
    handlers = _command_ids(_source("extension.ts"))
    assert declared - handlers == set(), "the palette offers a command nothing registers"
    assert handlers - declared == set(), "a command is registered but invisible in the palette"
    assert all(str(t).startswith("Raven: ") for t in titles.values()), titles
    # a keybinding or menu entry naming an undeclared command does nothing at all
    keyed = _command_ids(json.dumps(contributes.get("keybindings", [])))
    menued = _command_ids(json.dumps(contributes.get("menus", {})))
    assert keyed - declared == set()
    assert menued - declared == set()


def test_the_socket_url_follows_the_endpoint_and_invents_no_port() -> None:
    body = _source("config.ts")
    fn = body[body.index("export function getWsUrl") :]
    assert "'https:' ? 'wss' : 'ws'" in fn, "a TLS gateway would be dialed as plain ws"
    assert "18888" not in fn, "the socket falls back to a port the endpoint never named"
    assert "return null" in fn, "a bad endpoint is answered with a localhost socket"


def test_no_handler_is_typed_as_any() -> None:
    for path in SOURCES:
        assert not re.search(r"catch \(\w+:\s*any\)", path.read_text(encoding="utf-8")), path.name


def test_the_compiled_extension_is_not_tracked_as_a_second_copy() -> None:
    """`out/` was committed, so the tree carried two extensions.

    Measured before this wave removed it: the compiled copy was nine days older than `src/`, still
    fetched `/health`, still invented port 18888 for the socket, and registered 12 commands while the
    manifest this wave ships declares 13 -- so the palette offered **Raven: Set Gateway Token** with no
    handler behind it. `npm run compile` writes the directory from `src/` and `vscode:prepublish` calls it
    before packaging, which means the tracked copy was never what shipped; it was only what drifted.
    """
    assert "extension/vscode/out/" in (REPO / ".gitignore").read_text(encoding="utf-8")
    listed = subprocess.run(
        ["git", "ls-files", "-z", "extension/vscode/out"],
        cwd=str(REPO),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("this checkout has no git index to read")
    tracked = [name for name in listed.stdout.decode("utf-8", "replace").split("\0") if name]
    assert tracked == [], f"compiled output is tracked again: {tracked}"
