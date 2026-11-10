"""Every docs page must say in one line what it is, in its own words.

MkDocs Material writes `<meta name="description">` from a page's `description` front matter and
falls back to `site_description` when the page has none. With no front matter anywhere, all eleven
indexed pages published the same sentence: the duplicate-meta-description entry a search console
reports, and a snippet that describes the wrong page.

The values are parsed with the same YAML loader MkDocs uses, because an unquoted colon inside
`description: ...` is not a string a theme can read - it is a `mapping values are not allowed here`
error at build time, which is how this file earned its existence.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MKDOCS = ROOT / "mkdocs.yml"
DOCS_DIR = ROOT / "docs"

FLOOR = 50
CEILING = 155


def nav_pages() -> list[str]:
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    pages: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.endswith(".md"):
            pages.append(node)

    walk(config.get("nav") or [])
    return pages


def front_matter(page: str, text: str | None = None) -> dict[str, str]:
    body = (DOCS_DIR / page).read_text(encoding="utf-8") if text is None else text
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    parsed = yaml.safe_load("\n".join(block)) or {}
    assert isinstance(parsed, dict), page
    return {str(key): str(value) for key, value in parsed.items()}


def test_the_nav_is_the_page_list_this_guard_reads() -> None:
    """Both directions, without a hand-written page count that goes stale on every new page."""
    pages = nav_pages()
    published = {
        path.relative_to(DOCS_DIR).as_posix()
        for path in DOCS_DIR.rglob("*.md")
        if "archive" not in path.relative_to(DOCS_DIR).parts
    }
    assert set(pages) == published, {
        "published_but_not_in_nav": sorted(published - set(pages)),
        "in_nav_but_not_published": sorted(set(pages) - published),
    }
    assert "archive/fixes-history.md" not in pages, "the archive is not published, so it is not gated"
    for page in pages:
        assert (DOCS_DIR / page).exists(), page


def test_every_docs_page_carries_its_own_description() -> None:
    for page in nav_pages():
        description = front_matter(page).get("description", "")
        assert description, f"{page} has no description, so the site tagline is served in its place"
        assert FLOOR <= len(description) <= CEILING, (page, len(description))


def test_no_two_docs_pages_describe_themselves_the_same_way() -> None:
    seen: dict[str, str] = {}
    for page in nav_pages():
        description = front_matter(page).get("description", "")
        assert description not in seen, f"{page} repeats the description of {seen.get(description)}"
        seen[description] = page
    assert len(seen) == len(nav_pages())


def test_the_site_description_is_not_copied_into_a_page() -> None:
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    site_description = str(config["site_description"])
    assert FLOOR <= len(site_description) <= 160, len(site_description)
    for page in nav_pages():
        assert front_matter(page).get("description") != site_description, page


def test_the_front_matter_reader_detects_the_absence_it_forbids() -> None:
    without = "# Getting Started" + "\n" + "\n" + "Install with pipx."
    assert front_matter("index.md", text=without) == {}
    quoted = "---" + "\n" + 'description: "A page that says what it is, in one concrete line."' + "\n" + "---"
    assert front_matter("index.md", text=quoted)["description"].startswith("A page")
