"""The gateway has to answer for the SPA's own public files, not for the SPA.

`mount_spa` mounted `/assets` and let a catch-all return `index.html` for everything else, so a shipped
install served the brand woff2 files, the service worker, the manifest, the offline shell and the icons as
37 bytes of HTML with `content-type: text/html`. The console therefore rendered in `system-ui` in production
while looking correct under `vite dev`, which serves `public/` itself, and no browser test caught it because
`getComputedStyle().fontFamily` reports the declared stack whether or not the file behind it ever arrived.

Measured against this tree before the fix: 4 of these tests were red (the public sweep, the font's type, the
worker and the table's own coverage), and the 4 that were green are the ones the fix must not break — the
shell still owns client routes and directories, an escaping path still reaches no file, and `/api/*` still
404s instead of falling through.

The second half of this file answers the other direction of the same seam: a shipped page that asks the
bundle for a file, and a bundle that has to hold it. The SPA shell used to fill its tab from a `data:` URI
holding a chick emoji, which is the one icon slot a document can paint without the gateway ever being asked
for a byte — so the asset rules above had nothing to say about it. Every icon the pages, the manifest and
the service worker name is now a path, and these tests require that path to be a real file of the right
kind in `web/public`, because `mount_spa`'s fallback would hand the browser HTML for a favicon exactly as
it handed HTML for a font.
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from raven.core.spa import mount_spa

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PUBLIC = WEB / "public"

#: Every document a browser is handed with the bundle around it, including the page the gateway keeps in
#: Python so that a install without Node still answers.
_ICON_PAGES: tuple[tuple[str, Path], ...] = (
    ("the SPA shell", WEB / "index.html"),
    ("the offline shell", PUBLIC / "offline.html"),
    ("the gateway's web chat page", ROOT / "raven" / "channels" / "webchat" / "channel.py"),
)

#: A tag whose attribute values may hold `<` and `>`: a `data:` URI carries its own markup inside its
#: quotes, and a scanner that stops at the first `>` reports no link -- so the icon it was written to
#: refuse is the one it cannot see.
_LINK_TAG = re.compile(r'<link\b(?:[^<>]|"[^"]*"|\'[^\']*\')*>')
_REL = re.compile(r'\brel="([^"]+)"')
_HREF = re.compile(r'\bhref="([^"]+)"')
_TYPE = re.compile(r'\btype="([^"]+)"')
_STATIC_LIST = re.compile(r"const STATIC_ASSETS = \[(.*?)];", re.S)
_FONT_LIST = re.compile(r"const PRECACHE_FONTS = \[(.*?)];", re.S)
_NOTIFICATION_ART = re.compile(r'\b(?:icon|badge):\s*"([^"]+)"')
_LISTED_PATH = re.compile(r'"(/[^"]+)"')
_VIEW_BOX = re.compile(r'viewBox="[^"\s]+\s+[^"\s]+\s+([^"\s]+)\s+([^"\s]+)"')

#: Written by the build into `web/dist` rather than copied from `web/public`, so they are not probed here.
_BUILT_PATHS = {"/", "/index.html"}


def icon_links(text: str) -> list[tuple[str, str, str]]:
    """The `(rel, href, type)` of every link in a document that names an icon, `type` empty when undeclared."""
    links: list[tuple[str, str, str]] = []
    for tag in _LINK_TAG.findall(text):
        rel, href = _REL.search(tag), _HREF.search(tag)
        if rel is not None and href is not None and "icon" in rel.group(1):
            declared = _TYPE.search(tag)
            links.append((rel.group(1), href.group(1), declared.group(1) if declared else ""))
    return links


def listed_paths(text: str, declaration: re.Pattern[str]) -> list[str]:
    """The quoted paths inside one of the service worker's lists."""
    block = declaration.search(text)
    assert block is not None, "the service worker no longer holds the list this reads"
    return _LISTED_PATH.findall(block.group(1))


def tile_size(path: Path) -> tuple[int, int]:
    """The side a tile draws, read from the format it is written in."""
    if path.suffix == ".svg":
        match = _VIEW_BOX.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"{path.name} carries no viewBox to size a tile by"
        return (int(float(match.group(1))), int(float(match.group(2))))
    from PIL import Image

    return Image.open(path).size


# A real woff2 starts with `wOF2`; the bytes below are not a usable font, only distinguishable from HTML.
ASSETS: dict[str, bytes] = {
    "index.html": b"<!doctype html><title>the app</title>",
    "assets/app.js": b"console.log('bundle')",
    "assets/app.css": b":root{--x:1}",
    "fonts/IBMPlexSans-latin.woff2": b"wOF2\x00\x00\x00\x01font-bytes",
    "icons/icon-192.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    "icons/icon-192.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    "favicon.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    "favicon.ico": b"\x00\x00\x01\x00\x01\x00\x10\x10",
    "manifest.json": b'{"name":"Raven","icons":[]}',
    "offline.html": b"<!doctype html><title>offline</title>",
    "sw.js": b"self.addEventListener('install',()=>{});",
}


def _client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    for rel, data in ASSETS.items():
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    app = FastAPI()
    assert mount_spa(app, dist) is True
    return TestClient(app)


def test_every_public_asset_the_shipped_document_asks_for_comes_back_as_itself(tmp_path: Path) -> None:
    """Paths are the ones in the built `index.html`, `main.tsx` and `fonts.css` — not a sample. Each one is
    required to arrive with the type this file's own table declares for its extension, which is how the
    promise stays about the answer rather than about whether HTML happens to be the wrong shape."""
    from raven.core.spa import BUNDLE_MEDIA_TYPES

    client = _client(tmp_path)
    for rel, data in ASSETS.items():
        if rel.startswith("assets/") or rel == "index.html":
            continue
        response = client.get(f"/{rel}")
        assert response.status_code == 200, rel
        assert response.content == data, f"/{rel} returned the SPA shell instead of the file"
        announced = response.headers["content-type"].split(";")[0].strip()
        expected = BUNDLE_MEDIA_TYPES[Path(rel).suffix.lower()]
        assert announced == expected, (
            f"/{rel} answered {announced!r}, not {expected!r}: the browser reads a font, a worker and a "
            "manifest by their type, not by their bytes"
        )


def test_the_font_is_announced_as_a_font_by_this_file_not_by_the_os(tmp_path: Path, monkeypatch) -> None:
    """`@font-face` works from a wrong MIME in some browsers and not in others, and Firefox refuses a font
    it is not told is a font. `mimetypes` on this interpreter answers `(None, None)` for `.woff2`, so
    without an explicit table the file would arrive correctly and still be announced
    `application/octet-stream` — and on a Linux CI runner `mimetypes` does know `font/woff2`, which would
    let the promise pass here and fail on the machine the container ships from. Blinding the registry is
    the proof that the answer comes from the code."""
    monkeypatch.setattr(mimetypes, "guess_type", lambda _url, **_kw: (None, None))
    response = _client(tmp_path).get("/fonts/IBMPlexSans-latin.woff2")
    assert response.headers["content-type"].startswith("font/woff2"), response.headers["content-type"]


def test_the_service_worker_is_served_as_a_script_from_the_root_scope(tmp_path: Path) -> None:
    """Registered from `main.tsx` as `/sw.js`: served as HTML, `navigator.serviceWorker.register()` rejects
    the answer with a MIME error and the offline path never activates — silently, because the console still
    works online."""
    client = _client(tmp_path)
    response = client.get("/sw.js")
    assert response.content == ASSETS["sw.js"]
    content_type = response.headers["content-type"]
    assert content_type.startswith(("text/javascript", "application/javascript")), content_type


def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    """`/fonts` names a real directory in the bundle; reading it as a file would be a listing, not a font."""
    response = _client(tmp_path).get("/fonts")
    assert response.content == ASSETS["index.html"]


def test_a_client_side_route_still_gets_the_shell(tmp_path: Path) -> None:
    """The fix must not turn the fallback off: `/ide` is a React route, not a file, and belongs to the SPA."""
    client = _client(tmp_path)
    for path in ("/ide", "/analytics/sessions", "/settings/appearance"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content == ASSETS["index.html"], path


def test_a_path_that_escapes_the_bundle_is_not_a_file(tmp_path: Path) -> None:
    """The rule is 'serve the real file if there is one', so the traversal probe has to miss every branch
    of it — both by coming back as the shell and by never reading the byte outside `dist`."""
    (tmp_path / "secret.txt").write_bytes(b"outside the bundle")
    client = _client(tmp_path)
    for probe in ("/../secret.txt", "/%2e%2e/secret.txt", "/fonts/../../secret.txt", "/..%2fsecret.txt"):
        response = client.get(probe)
        assert response.content != b"outside the bundle", f"{probe} escaped web/dist"


def test_the_api_namespace_never_reaches_the_asset_layer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/does-not-exist").status_code == 404


def test_the_media_table_covers_every_extension_the_bundle_asks_for() -> None:
    """A guard over the fix's own coverage: `web/public` is what the shipped document requests outside
    `/assets`, and an extension missing from the table is a file whose type gets guessed from the host's
    registry again. Read off the directory, so a new face or icon cannot arrive without a media type."""
    from raven.core.spa import BUNDLE_MEDIA_TYPES

    requested = {p.suffix.lower() for p in WEB.joinpath("public").rglob("*") if p.is_file()}
    assert requested, "web/public holds nothing: the probe is broken, not the bundle empty"
    missing = sorted(requested - set(BUNDLE_MEDIA_TYPES))
    assert not missing, f"files under web/public with no media type in spa.py: {missing}"


def test_the_link_reader_reads_a_tag_whose_value_holds_markup() -> None:
    """The scanner's own floor, planted on the shape this repository actually shipped.

    A `data:` URI favicon is full of `<` and `>`, so a tag reader that stops at the first angle bracket
    finds no link in the document, reports the page clean, and lets back in the exact icon the test below
    refuses. This is the probe that says the sweep is looking at the link rather than at nothing.
    """
    chick = (
        '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/'
        "2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#x1F426;</text></svg>\" />"
    )
    links = icon_links(chick)
    assert len(links) == 1, f"a link whose href holds `<svg>` was read as {len(links)} links"
    assert links[0][0] == "icon" and links[0][1].startswith("data:"), links
    assert links[0][2] == "image/svg+xml", f"the reader took the href and lost the declared type: {links}"
    assert icon_links('<link rel="stylesheet" href="/styles.css" />') == [], "a link that names no icon counted"


def test_the_icon_a_shipped_page_links_is_a_file_the_bundle_carries() -> None:
    """Each page names its tab icon as a path, and the path has to be a file `web/public` holds.

    A `data:` URI is how the shell escaped this promise for a whole wave: the document paints it without
    asking the gateway for anything, so the brand in the tab was a glyph from whatever font the reader's
    system happens to hold, at a size no stylesheet sets and in a colour no theme moves. A relative or
    missing path is the other way to lose it — `mount_spa`'s fallback answers both with the SPA shell, and
    a favicon made of HTML is a globe in the tab and nothing in the console.
    """
    for label, page in _ICON_PAGES:
        links = icon_links(page.read_text(encoding="utf-8"))
        assert links, f"{label} links no icon at all, so the tab falls back to the browser's own mark"
        assert len(links) >= 2, f"{label} carries {len(links)} icon link, not the vector and its fallback"
        hrefs: set[str] = set()
        for rel, href, _declared in links:
            assert not href.startswith("data:"), f"{label} links {rel} as a data URI instead of the bundle"
            assert href.startswith("/"), f"{label} links {rel} as {href!r}, which is not a bundle path"
            target = PUBLIC / href.removeprefix("/")
            assert target.is_file(), f"{label} links {rel} at {href} and web/public holds no such file"
            hrefs.add(href)
        assert "/favicon.svg" in hrefs, f"{label} never points the tab at the brand vector: {sorted(hrefs)}"


def test_the_type_a_page_announces_for_an_icon_is_the_type_the_gateway_answers(tmp_path: Path) -> None:
    """A `type` attribute is a promise about the response header, and three pages made the wrong one.

    Every page announces `/favicon.ico` as `image/vnd.microsoft.icon` -- the registered type -- while the asset
    layer answered it `image/x-icon`, the name the Windows registry publishes. Nothing broke visibly: a browser
    decodes an icon from its bytes and ignores the attribute, which is how a promise the server contradicts
    survived here and in the built bundle, where the preview server repeats the same answer. Measured through
    the mounted bundle rather than against the table, so the claim is about the response a reader gets and
    holds whatever the host's registry says.
    """
    client = _client(tmp_path)
    declared = 0
    for label, page in _ICON_PAGES:
        for rel, href, announced in icon_links(page.read_text(encoding="utf-8")):
            if not announced:
                continue
            declared += 1
            answered = client.get(href).headers["content-type"].split(";")[0].strip()
            assert answered == announced, (
                f"{label} announces {rel} at {href} as {announced!r} and the gateway answers it {answered!r}"
            )
    assert declared >= 3, f"only {declared} icon links declared a type, so the sweep above compared nothing"


def test_a_slot_that_takes_only_a_raster_is_given_a_raster() -> None:
    """`apple-touch-icon` and a notification's `icon`/`badge` are filled from a bitmap or from nothing.

    iOS does not read an SVG in the touch slot: the home screen gets a black square with the mark missing
    and no error anywhere a developer looks. Chrome is the same about a notification badge — it renders the
    badge's alpha channel, and an SVG has no alpha channel for it to take.
    """
    for label, page in _ICON_PAGES:
        for rel, href, _declared in icon_links(page.read_text(encoding="utf-8")):
            if rel != "apple-touch-icon":
                continue
            assert href.endswith(".png"), f"{label} puts {href} in the touch slot, which takes a raster only"
            assert (PUBLIC / href.removeprefix("/")).is_file(), f"{label} links a touch icon the bundle lacks"

    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    art = _NOTIFICATION_ART.findall(worker)
    assert art, "the service worker declares no notification art, so this probe would pass on an empty list"
    for href in art:
        assert href.endswith(".png"), f"a notification is asked to paint {href}, which no browser fills from SVG"
        assert (PUBLIC / href.removeprefix("/")).is_file(), f"the worker names {href} and the bundle lacks it"


def test_the_manifest_promises_icons_the_bundle_carries_at_the_size_it_declares() -> None:
    """An install tile is chosen from this list alone, so a wrong `type` or `sizes` is a blurry or blank
    home screen that no page can repair — the installer never reads the console's HTML."""
    from raven.core.spa import BUNDLE_MEDIA_TYPES

    icons = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))["icons"]
    assert icons, "manifest.json declares no icons, so an install has nothing to put on the home screen"
    for icon in icons:
        src = icon["src"]
        assert src.startswith("/"), f"manifest.json asks for {src} relative to whatever page installed it"
        target = PUBLIC / src.removeprefix("/")
        assert target.is_file(), f"manifest.json asks for {src} and web/public holds no such file"
        assert icon["type"] == BUNDLE_MEDIA_TYPES[target.suffix.lower()], (
            f"{src} is announced as {icon['type']}, which is not the type the gateway answers it with"
        )
        declared = tuple(int(part) for part in icon["sizes"].split("x"))
        drawn = tile_size(target)
        assert declared == drawn, f"{src} declares {declared} and the file draws {drawn}"


def test_everything_the_service_worker_precaches_is_a_file_the_bundle_carries() -> None:
    """One missing entry rejects the whole install, so the offline path dies for a typo in a list.

    The brand icons belong in this list for the same reason the faces do: an install that opens offline
    with no cached favicon gets the globe, which is the symptom this wave was about.
    """
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    static = listed_paths(worker, _STATIC_LIST)
    fonts = listed_paths(worker, _FONT_LIST)
    assert static and fonts, "the worker holds no lists to read, so nothing below is checked"
    for href in [*static, *fonts]:
        if href in _BUILT_PATHS:
            continue
        assert (PUBLIC / href.removeprefix("/")).is_file(), (
            f"the worker precaches {href}, which the bundle does not carry: install rejects every entry"
        )
    for href in ("/favicon.svg", "/favicon.ico"):
        assert href in static, f"{href} is not precached, so an install opened offline loses its tab icon"


def test_the_tab_icon_the_app_ships_is_the_one_the_landing_ships() -> None:
    """One drawing, one set of bytes: a re-typed copy is how the product came to wear two marks."""
    shipped = (PUBLIC / "favicon.svg").read_bytes()
    original = (ROOT / "site" / "favicon.svg").read_bytes()
    assert shipped == original, "web/public/favicon.svg is not the landing's tab icon -- run make_web_icons.py"


def _icon_generator(monkeypatch: MonkeyPatch) -> ModuleType:
    """The app-icon generator, loaded the way a test can load a script.

    `make_web_icons.py` imports `icon_render` by script-directory precedence, which a pytest run does not
    give it, so the dependency is loaded first and installed under the name the import asks for.
    """

    def load(name: str) -> ModuleType:
        import importlib.util

        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    monkeypatch.setitem(sys.modules, "icon_render", load("icon_render"))
    return load("make_web_icons")


def test_the_icon_generator_notices_a_shipped_file_that_is_not_the_mark(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """`make_web_icons.py --check` is the command an operator runs before shipping, so it has to answer the
    same promise the guards above measure and fail on the same mistakes. Pointed at a copy of the bundle with
    two files spoiled, it names exactly those two: the vector an edit moved, and the raster whose pixels are
    no longer the render. A `--check` that only ever says "current" is a gate that reports no failures."""
    import shutil

    writer = _icon_generator(monkeypatch)
    bundle = tmp_path / "public"
    shutil.copytree(PUBLIC, bundle)
    monkeypatch.setattr(writer, "FAVICON_SVG", bundle / "favicon.svg")
    monkeypatch.setattr(writer, "FAVICON_ICO", bundle / "favicon.ico")
    monkeypatch.setattr(writer, "VECTOR_TILES", {192: bundle / "icons" / "icon-192.svg"})
    monkeypatch.setattr(writer, "RASTER_TILES", {192: bundle / "icons" / "icon-192.png"})

    assert writer.drift() == [], f"a healthy bundle was not current: {writer.drift()}"

    (bundle / "favicon.svg").write_text(
        (bundle / "favicon.svg").read_text(encoding="utf-8").replace('fill="#d946ef"', 'fill="#ff0055"'),
        encoding="utf-8",
    )
    from PIL import Image

    Image.new("RGBA", (96, 96), (0, 0, 0, 0)).save(bundle / "icons" / "icon-192.png", format="PNG")
    assert writer.drift() == ["favicon.svg", "icon-192.png"], writer.drift()
