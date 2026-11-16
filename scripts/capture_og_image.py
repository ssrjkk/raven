"""Capture the landing page's opening screen as the site's two screenshots.

Both are the viewport itself, not the `.hero` element: an element shot is whatever height the box
happens to be -- 943px at 1200 wide, 965px at 1440 -- and neither consumer accepts an arbitrary
size. The social card is 1200x630, the figure the Open Graph spec asks for, and it carries the pitch,
the handshake and the switch over the two routes. The README band is 1440x1030, the height at which
the whole hero section fits: the install blocks run 671-941 at that width, so a 900px frame saws the
client config through the closing braces.

The shot is refused if the opening sequence has not settled, and refused if the frame cuts anything
that card has to hold whole, because a card with a half-faded line of the pitch on it is worse than
no card.

    python scripts/capture_og_image.py --only both --channel chrome
"""

import argparse
import http.server
import struct
import sys
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CARDS: dict[str, tuple[Path, int, int]] = {
    "og": (SITE / "og-image.png", 1200, 630),
    "readme": (ROOT / "docs" / "screenshots" / "hero.png", 1440, 1030),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    "og": (".hero-copy", ".console", ".transport-switch"),
    "readme": (".hero-copy", ".console", ".hero-install", ".hero-install-note"),
}

# The hero entrance ends around 850ms after load; the settle check below is what actually guards
# the frame, this is only how long the page is allowed to take getting there.
SETTLE_MS = 2500

_OPACITY = "(els => els.every(el => getComputedStyle(el).opacity === '1'))"
_CUT = """(sels => sels
    .map(sel => document.querySelector(sel))
    .filter(el => el !== null)
    .filter(el => {
        const box = el.getBoundingClientRect();
        return box.bottom > innerHeight || box.right > innerWidth;
    })
    .map(el => '.' + el.className))"""


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_port


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    return struct.unpack(">II", data[16:24])


def capture(names: list[str], channel: str | None) -> int:
    from playwright.sync_api import sync_playwright

    server, port = serve(SITE)
    failures: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel) if channel else playwright.chromium.launch()
            try:
                for name in names:
                    path, width, height = CARDS[name]
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(f"http://127.0.0.1:{port}/index.html")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(SETTLE_MS)
                    page.evaluate("window.scrollTo(0, 0)")
                    problems = []
                    if not page.eval_on_selector_all(".hero-copy > *", _OPACITY):
                        problems.append(f"a hero line was still fading at {SETTLE_MS}ms")
                    if cut := page.evaluate(_CUT, list(REQUIRED[name])):
                        problems.append(f"the {width}x{height} frame cuts {', '.join(cut)}")
                    if problems:
                        failures.append(f"{name}: {'; '.join(problems)}")
                        page.close()
                        continue
                    page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": width, "height": height})
                    written = png_size(path)
                    if written != (width, height):
                        failures.append(f"{name}: wrote {written}, wanted {(width, height)}")
                        page.close()
                        continue
                    print(f"Saved {path.relative_to(ROOT)} ({written[0]}x{written[1]}, {path.stat().st_size} bytes)")
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
    for message in failures:
        print(f"ERROR: {message}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=[*CARDS, "both"], default="both")
    parser.add_argument(
        "--channel",
        default=None,
        help="a Chrome channel instead of the browser Playwright downloaded, e.g. `chrome`",
    )
    args = parser.parse_args()
    names = list(CARDS) if args.only == "both" else [args.only]
    return capture(names, args.channel)


if __name__ == "__main__":
    sys.exit(main())
