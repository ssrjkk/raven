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
import shutil
import subprocess
from html.parser import HTMLParser
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


class _ScriptBlock(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._inside = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._inside = self._inside or tag == "script"

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside = False


# The expressions the webview template interpolates, with the value the extension host holds for each
# when the panel opens. `fontRoot` is printed by the host from the granted asset directory, so its real
# shape is a `vscode-webview://` URI whose authority is a per-install secret hash -- the reader and node
# are both fed the same preview of it, which is what makes the byte-for-byte comparison below about the
# template and not about the machine it ran on.
PREVIEW_WS_URL = "ws://127.0.0.1:8790/ws"
PREVIEW_FONT_ROOT = "vscode-webview://0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d/assets/fonts"
_EXPRESSION = re.compile(r"\$\{([^}]*)\}")
_ESCAPES_THAT_MEAN_THEMSELVES = {"\\", "`", "$"}
_CONTROL_ESCAPES = {"n": "\n", "r": "\r", "t": "\t"}


def _interpolations(ws_url: str) -> dict[str, str]:
    return {"JSON.stringify(wsUrl)": json.dumps(ws_url), "fontRoot": PREVIEW_FONT_ROOT}


_NODE_RENDERER = """
// Cook panel.ts's webview template with the engine that evaluates it, then parse every script block the
// produced document carries, which is what the webview has to do with it.
import { readFileSync, writeFileSync } from "node:fs";
import vm from "node:vm";

const [panelPath, outPath, wsUrl, fontRoot] = process.argv.slice(2);
const src = readFileSync(panelPath, "utf8");
const start = src.indexOf("`<!DOCTYPE html");
if (start < 0) {
  console.log("no webview template in " + panelPath);
  process.exit(2);
}
let html = "";
try {
  html = vm.runInNewContext(src.slice(start, src.lastIndexOf("`") + 1), { wsUrl, fontRoot, JSON });
} catch (err) {
  console.log("the template does not evaluate: " + err.message);
  process.exit(1);
}
const blocks = [...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)];
for (const [i, m] of blocks.entries()) {
  try {
    new vm.Script(m[1]);
  } catch (err) {
    console.log("script " + i + " of the shipped document does not parse: " + err.message);
    process.exit(1);
  }
}
writeFileSync(outPath, html);
console.log("ok blocks=" + blocks.length + " bytes=" + html.length);
"""


def _webview_literal(source: str) -> str:
    """The body of the template literal the panel returns, ended where a JS engine ends one: at the first
    backtick that is not escaped. A comment carrying one cuts the document in half, and this is where the
    reader notices."""
    start = source.index("`<!DOCTYPE html")
    i = start + 1
    while True:
        if i >= len(source):
            raise AssertionError("the webview template never closes")
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            return source[start + 1 : i]
        if source.startswith("${", i):
            close = source.index("}", i + 2)
            assert "`" not in source[i + 2 : close], "the webview interpolates a nested literal"
            i = close + 1
            continue
        i += 1


def _cook(literal: str, interpolated: dict[str, str]) -> tuple[str, list[str]]:
    """The text a JS engine makes of a template literal body, plus the escapes it consumed on the way."""
    out: list[str] = []
    hazards: list[str] = []
    i = 0
    while i < len(literal):
        ch = literal[i]
        if ch == "\\":
            following = literal[i + 1 : i + 2]
            if following in _ESCAPES_THAT_MEAN_THEMSELVES:
                out.append(following)
            else:
                line = literal[:i].count("\n") + 1
                hazards.append(f"line {line}: a backslash before {following!r}")
                out.append(_CONTROL_ESCAPES.get(following, following))
            i += 2
            continue
        if literal.startswith("${", i):
            close = literal.index("}", i + 2)
            expression = literal[i + 2 : close]
            if expression not in interpolated:
                raise AssertionError(
                    f"the webview template interpolates {expression!r}, which this reader does not model"
                )
            out.append(interpolated[expression])
            i = close + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), hazards


def render_webview(source: str, *, ws_url: str = PREVIEW_WS_URL) -> str:
    """The document the extension host hands the webview, cooked the way the host cooks it."""
    document, hazards = _cook(_webview_literal(source), _interpolations(ws_url))
    assert not hazards, "the escapes the panel writes are not the ones the document gets: " + "; ".join(hazards)
    assert document.endswith("</html>"), "the webview template ends inside the document, so the panel ships half a page"
    return document


def _node_cook(panel_path: pathlib.Path, tmp_path: pathlib.Path, ws_url: str = PREVIEW_WS_URL) -> bytes:
    renderer = tmp_path / "cook.mjs"
    rendered = tmp_path / "panel.html"
    renderer.write_text(_NODE_RENDERER, encoding="utf-8")
    cooked = subprocess.run(
        ["node", str(renderer), str(panel_path), str(rendered), ws_url, PREVIEW_FONT_ROOT],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert cooked.returncode == 0, cooked.stdout.decode("utf-8", "replace") + cooked.stderr.decode("utf-8", "replace")
    return rendered.read_bytes()


def _panel_script() -> str:
    """The inline script of the chat panel, read the way a browser reads it.

    Two things stand between `panel.ts` and the bytes the webview executes: the host evaluates a template
    literal, so every escape in it is consumed before the document exists, and HTML closes a script block
    at the matching tag, not at the first `</script>` anywhere in the text. Grepping the source for the
    shipped behaviour measures neither: the `\\n` the source writes inside `split('...')` is a real newline
    by the time the document has it, which is a syntax error the browser refuses to run while the suite
    stayed green.
    """
    parser = _ScriptBlock()
    parser.feed(render_webview(_source("panel.ts")))
    script = "".join(parser.chunks)
    assert script.strip(), "the chat panel has no script block"
    return script


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


# --- what the webview is handed, as opposed to what the source says ---


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_document_the_host_makes_matches_the_document_the_reader_cooks(tmp_path: pathlib.Path) -> None:
    """The cook above is a re-implementation of a JS engine's rule, so it is measured against that engine
    on the same file: byte for byte, and every script block of the produced document has to parse.

    Measured before this guard existed: the panel's stylesheet carried a comment with backticks in it,
    which ended the literal where the host evaluates it, and `split('\\n')` in the source is a split on a
    raw newline in the document. Both left the shipped extension with a page whose script never runs -- the
    socket is opened by that script -- while every assertion in this file stayed green on the source text.

    Both sides are handed the same preview values, and a wsUrl neither side has hardcoded, so the equality
    below can only hold if each cook really reads the interpolation out of the template.
    """
    ws_url = "ws://127.0.0.1:8799/ws"
    cooked = _node_cook(EXT / "src" / "panel.ts", tmp_path, ws_url)
    assert cooked == render_webview(_source("panel.ts"), ws_url=ws_url).encode("utf-8")


def test_the_reader_models_every_expression_the_template_interpolates() -> None:
    """An expression the reader does not model is a value the document ships with the reader's guess in
    its place, and the byte-for-byte guard would then be comparing two cooks of the same wrong document.
    So the modelled set is checked against the template in both directions."""
    found = set(_EXPRESSION.findall(_webview_literal(_source("panel.ts"))))
    modelled = set(_interpolations(PREVIEW_WS_URL))
    assert found == modelled, f"template {sorted(found)} vs reader {sorted(modelled)}"


def test_the_document_reader_notices_an_interpolation_it_does_not_model() -> None:
    source = _source("panel.ts")
    planted = source.replace("${fontRoot}", "${webviewUriOfFontRoot}", 1)
    assert planted != source, "panel.ts no longer interpolates fontRoot, so nothing was planted"
    with pytest.raises(AssertionError, match="does not model"):
        render_webview(planted)


def test_the_fence_the_panel_renders_survives_the_template_being_evaluated() -> None:
    """A backslash written once inside a template literal is consumed there, so a regex class or a newline
    escape has to be doubled to reach the document at all."""
    script = _panel_script()
    assert r"/(```\w*\n?[\s\S]*?```)/g" in script, "the fence split reaches the browser without its classes"
    assert r"/^```(\w*)\n?([\s\S]*?)```$/" in script, "the fence match reaches the browser without its classes"
    assert r"part.split('\n')" in script, "the line split reaches the browser as a literal newline"


def test_the_document_reader_notices_an_escape_the_engine_consumes() -> None:
    planted = {
        "a newline the engine eats before the document gets it": (r"part.split('\\n')", r"part.split('\n')"),
        "a regex class the engine eats": (r"\`\`\`\\w*\\n?", r"\`\`\`\w*\n?"),
    }
    source = _source("panel.ts")
    for label, (written, broken) in planted.items():
        assert written in source, f"panel.ts no longer writes {written}, so {label} was never planted"
        with pytest.raises(AssertionError, match="backslash"):
            render_webview(source.replace(written, broken))


def test_a_backtick_in_the_pages_own_css_cuts_the_shipped_document_short() -> None:
    source = _source("panel.ts")
    planted = source.replace("#header h1 {", "`#header h1` {", 1)
    assert planted != source, "panel.ts no longer styles the header, so nothing was planted"
    with pytest.raises(AssertionError, match="ends inside the document"):
        render_webview(planted)


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
