"""Fail the docs deploy when a built page or stylesheet fetches from another host.

The landing-site tests already prove ``site/`` makes no third-party request. This is the
same invariant for the MkDocs output the deploy stages under ``/docs``: Material's default
theme pulls Roboto from Google Fonts, and the previous shell pipeline passed a build that
wrote nothing at all. Standard library only — the workflow installs MkDocs, not the
project's runtime dependencies.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PUBLISHED = "https://ssrjkk.github.io/"
TAG_REF = re.compile(
    r'<(?:link|script|img|source|iframe|video|audio)\b[^>]*?\b(?:href|src)="(https?://[^"]+)"',
    re.IGNORECASE,
)
CSS_REF = re.compile(r"""url\(\s*['"]?(https?://[^)'"]+)""", re.IGNORECASE)


def offsite_references(root: Path) -> set[str]:
    found: set[str] = set()
    for page in root.rglob("*.html"):
        text = page.read_text(encoding="utf-8", errors="replace")
        found |= {url for url in TAG_REF.findall(text) if not url.startswith(PUBLISHED)}
    for sheet in root.rglob("*.css"):
        text = sheet.read_text(encoding="utf-8", errors="replace")
        found |= {url for url in CSS_REF.findall(text) if not url.startswith(PUBLISHED)}
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "build/docs")
    if not (root / "index.html").is_file():
        sys.stderr.write(f"::error::mkdocs wrote no documentation to {root}\n")
        return 1
    refs = offsite_references(root)
    if refs:
        sys.stderr.write(
            f"::error::built documentation fetches from another host: {sorted(refs)}\n"
        )
        return 1
    sys.stdout.write(f"checked {root}: no third-party asset request\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
