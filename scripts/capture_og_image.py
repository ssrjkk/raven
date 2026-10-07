"""Capture the hero section as a 1200x630 og:image."""
import http.server
import os
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).parent.parent / "site"
OUTPUT = SITE / "og-image.png"


def capture() -> None:
    os.chdir(SITE)
    server = http.server.HTTPServer(
        ("127.0.0.1", 0),
        http.server.SimpleHTTPRequestHandler,
    )
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.goto(f"http://127.0.0.1:{port}/index.html")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
            hero = page.query_selector(".hero")
            if hero:
                hero.screenshot(path=str(OUTPUT))
                print(f"Saved {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
            else:
                print("ERROR: .hero not found", file=sys.stderr)
                sys.exit(1)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    capture()
