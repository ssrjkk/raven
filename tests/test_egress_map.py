"""Every outbound host named in the product source must be on the map in docs/security/egress.md.

The landing page tells users the assistant reaches no third-party asset host and no service of ours.
That is only a sentence until something checks it, so this file checks two things: the map covers the
code (a new host literal cannot be merged unannounced), and the shipped web surfaces load nothing
off their own origin.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "security" / "egress.md"
PACKAGES = ("raven", "ravencode", "aios")

_URL = re.compile(r"https?://([^\s'\"\\/?#]+)")
_TABLE_ROW = re.compile(r"^\|\s*(.+?)\s*\|")
_CELL_TOKEN = re.compile(r"`([^`]+)`")
_TEMPLATE = re.compile(r"\{[^}]*\}")

# Hosts the source builds entirely from a runtime value, so no label survives to match against.
# "*" is the node address in raven/cli/nodes_cmd.py -- see "LAN and paired devices" in the map.
_UNRESOLVABLE = frozenset({"*"})

# Hosts a third-party client assembles itself, so our source holds no literal to match. The
# exemption has to be earned: `proof` must still appear in the named file, which is the call that
# reaches the host. Delete the call and the map row loses its basis and fails.
_SDK_OWNED: dict[str, tuple[str, str]] = {
    "huggingface.co": ("raven/unique/fine_tuning.py", "from_pretrained"),
    "api.wandb.ai": ("raven/unique/fine_tuning.py", "import wandb"),
}


def _netloc(raw: str) -> str:
    """Host part of a URL literal: no userinfo, no port, no trailing dot, and any `{template}` slot
    becomes the wildcard the map documents."""
    host = raw.rsplit("@", 1)[-1]
    host = _TEMPLATE.sub("*", host)
    return host.split(":")[0].strip("._)\"',").lower()


def documented_tokens() -> set[str]:
    tokens: set[str] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        row = _TABLE_ROW.match(line)
        if not row or row.group(1).startswith("---") or row.group(1).lower().startswith("host"):
            continue
        tokens.update(token.strip().lower() for token in _CELL_TOKEN.findall(row.group(1)))
    return tokens


def code_hosts() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for package in PACKAGES:
        for py in sorted((ROOT / package).rglob("*.py")):
            text = py.read_text(encoding="utf-8-sig", errors="replace")
            for match in _URL.finditer(text):
                host = _netloc(match.group(1))
                if not host:
                    continue
                found.setdefault(host, []).append(str(py.relative_to(ROOT)))
    return found


def _covers(host: str, token: str) -> bool:
    if fnmatch.fnmatch(host, token):
        return True
    if "*" not in token:
        prefix = token.rstrip(".")
        return host == prefix or host.startswith(prefix + ".") or (host.endswith("*") and host.startswith(prefix))
    return False


def test_every_host_literal_in_the_product_is_on_the_map() -> None:
    tokens = documented_tokens()
    unmapped = {
        host: files
        for host, files in code_hosts().items()
        if host not in _UNRESOLVABLE and not any(_covers(host, token) for token in tokens)
    }
    assert not unmapped, f"hosts missing from {DOC.name}: {unmapped}"


def test_the_unresolvable_set_is_still_unresolvable() -> None:
    # a token-less host is a deliberate exception, so it must disappear from the list when the source
    # stops building a host from a runtime value
    built = set(code_hosts())
    dead = sorted(token for token in _UNRESOLVABLE if token not in built)
    assert not dead, f"no source builds these any more: {dead}"


def test_the_map_names_no_host_the_code_stopped_using() -> None:
    present = set(code_hosts())
    stale = sorted(
        token
        for token in documented_tokens()
        if "*" not in token
        and token not in _SDK_OWNED
        and not any(host == token.rstrip(".") or host.startswith(token.rstrip(".") + ".") for host in present)
    )
    assert not stale, f"map rows with no matching host literal in {PACKAGES}: {stale}"


@pytest.mark.parametrize("host", sorted(_SDK_OWNED))
def test_an_sdk_owned_host_is_still_reached_by_the_call_that_earns_it(host: str) -> None:
    """A row with no host literal is the one way this map could start describing a socket nobody
    opens. The proof is the call: remove it and the row is unverifiable, so it must go."""
    where, proof = _SDK_OWNED[host]
    source = (ROOT / where).read_text(encoding="utf-8")
    assert proof in source, f"{where} no longer contains {proof!r}; drop the {host} row or restore the call"


def _external_refs(markup: str) -> list[str]:
    return [
        value
        for value in re.findall(r"(?:src|href)\s*=\s*\"([^\"]+)\"", markup)
        if re.match(r"(?:https?:)?//", value)
    ]


def test_shipped_web_pages_load_nothing_from_another_host() -> None:
    from raven.channels.webchat.channel import INDEX_HTML

    spa = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    popup = (ROOT / "extension" / "src" / "popup" / "index.html").read_text(encoding="utf-8")
    for label, markup in (("SPA", spa), ("webchat fallback", INDEX_HTML), ("extension popup", popup)):
        assert not _external_refs(markup), f"{label} references an off-origin asset: {_external_refs(markup)}"


def test_spa_fonts_are_vendored_with_a_cyrillic_subset() -> None:
    raw = (ROOT / "web" / "src" / "styles" / "fonts.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)  # the header comment names the origin it replaced
    assert "fonts.googleapis.com" not in css
    faces = re.findall(r"@font-face \{.*?\}", css, re.S)
    assert faces, "no @font-face rules"
    for rule in faces:
        local = re.search(r"url\('(/fonts/[^']+)'\)", rule)
        assert local, f"font rule without a local url: {rule[:80]}"
        assert (ROOT / "web" / "public" / local.group(1).lstrip("/")).is_file(), local.group(1)
    cyrillic = [rule for rule in faces if "U+0400-045F" in rule]
    assert cyrillic, "no cyrillic subset: Russian text would fall back to a system font"
    families: set[str] = set()
    for rule in cyrillic:
        found = re.search(r"font-family: '([^']+)'", rule)
        assert found is not None
        families.add(found.group(1))
    assert families == {"Inter", "JetBrains Mono"}, "the cyrillic subset must cover both families"


def test_extension_manifest_forbids_remote_and_inline_code() -> None:
    manifest: dict[str, Any] = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    policy = manifest["content_security_policy"]["extension_pages"]
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy
    assert manifest["manifest_version"] == 3
