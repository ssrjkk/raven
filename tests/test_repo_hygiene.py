# ruff: noqa: RUF001 (intentional Cyrillic in the transcript fixture)
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The exporter's header, not its file name. A rule that remembered `<topic>_<date>_<hh-mm>.md` let a
# hand-renamed transcript (`raven!!!.md`, 1,665,107 bytes) into a public commit, where it also answered
# every repo-wide `git grep` with chat text instead of code. Only Markdown is read: this file quotes the
# markers itself, and a gate that scanned its own source would report itself forever.
_EXPORT_MARKERS = ("**Exported:**", "### **You**")
_SCANNED_SUFFIXES = {".md"}


def _git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, timeout=60, check=False)


def _tracked_files() -> list[str]:
    listed = _git(["ls-files", "-z"])
    if listed.returncode != 0:
        return []
    return [name.decode("utf-8", "replace") for name in listed.stdout.split(b"\0") if name]


def _is_chat_export(text: str) -> bool:
    return all(marker in text for marker in _EXPORT_MARKERS)


def _tracked_chat_exports(names: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for name in _tracked_files() if names is None else names:
        if pathlib.PurePosixPath(name).suffix not in _SCANNED_SUFFIXES:
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _is_chat_export(text):
            found.append(name)
    return sorted(found)


def _ignored(path: str) -> bool:
    return _git(["check-ignore", "--no-index", "-q", path]).returncode == 0


def test_the_detector_separates_a_transcript_from_a_document() -> None:
    transcript = (
        "# Аудит и улучшение проекта\n\n"
        "**Exported:** 2026-11-14T23:20:17.647Z\n\n"
        "**Work Directory:** `D:\\raven`\n\n---\n\n### **You**\n\nдальше что делать?\n"
    )
    assert _is_chat_export(transcript)
    assert not _is_chat_export("# Changelog\n\n## Unreleased\n\n### Fixed\n\n- a gate that bites\n")
    # one marker alone is a quotation, not an export
    assert not _is_chat_export("The exporter writes **Exported:** at the top of every file.")


def test_the_scan_reads_the_index_and_the_marker(tmp_path: pathlib.Path) -> None:
    """End to end, not just the detector: a transcript the index owns has to come back by name."""
    transcript = tmp_path / "renamed-by-hand.md"
    transcript.write_text("**Exported:** 2026-11-14T23:20:17.647Z\n\n### **You**\n\nhi\n", encoding="utf-8")
    assert _tracked_chat_exports([str(transcript)]) == [str(transcript)]


def test_the_sweep_is_not_vacuous() -> None:
    tracked = _tracked_files()
    assert len(tracked) > 500, f"index read returned {len(tracked)} names"
    assert "README.md" in tracked
    scanned = [name for name in tracked if pathlib.PurePosixPath(name).suffix in _SCANNED_SUFFIXES]
    assert len(scanned) > 20, f"only {len(scanned)} Markdown files would be read"


def test_no_tracked_file_is_a_chat_export() -> None:
    assert _tracked_chat_exports() == []


@pytest.mark.parametrize("name", ["raven!!!.md", "Аудит_и_улучшение_проекта_2026-11-15_02-32.md", "anything.md"])
def test_a_transcript_is_ignored_under_any_root_name(name: str) -> None:
    assert _ignored(name), f"{name} would be staged by `git add -A`"


@pytest.mark.parametrize("name", ["README.md", "README.ru.md", "AGENTS.md", "CHANGELOG.md", "SECURITY.md"])
def test_the_published_root_documents_stay_trackable(name: str) -> None:
    assert not _ignored(name), f"{name} is ignored, so an edit to it could never be committed"


def test_docs_below_the_root_are_not_swept_by_the_rule() -> None:
    assert not _ignored("docs/archive/fixes-history.md")


# AGENTS.md: "Record notable changes in CHANGELOG.md — do not grow this file with fix logs." Prose did
# not hold: the Unreleased block reached 1590 lines and 329,310 bytes, roughly one bullet per commit.
# Released sections below it grow legitimately with each version, so the budget sits on Unreleased.
_UNRELEASED_LINE_BUDGET = 80
_UNRELEASED_BULLET_BUDGET = 60
_CHANGELOG = ROOT / "CHANGELOG.md"


def _unreleased_section(text: str) -> str:
    start = re.search(r"^## \[Unreleased\][ \t]*$", text, re.M)
    if start is None:
        return ""
    rest = text[start.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _over_budget(text: str) -> list[str]:
    section = _unreleased_section(text)
    lines = section.splitlines()
    bullets = [line for line in lines if line.startswith("- ")]
    problems: list[str] = []
    if len(lines) > _UNRELEASED_LINE_BUDGET:
        problems.append(f"{len(lines)} lines exceeds {_UNRELEASED_LINE_BUDGET}")
    if len(bullets) > _UNRELEASED_BULLET_BUDGET:
        problems.append(f"{len(bullets)} bullets exceeds {_UNRELEASED_BULLET_BUDGET}")
    return problems


def test_the_section_reader_stops_at_the_next_release() -> None:
    text = (
        "# Changelog\n\nA duplicate `## [Unreleased]` block is archived elsewhere.\n\n"
        "## [Unreleased]\n\n### Fixed\n- one notable thing\n\n"
        "## [0.4.8] - 2026-09-22\n\n### Changed\n- a released thing\n"
    )
    section = _unreleased_section(text)
    assert "- one notable thing" in section
    assert "a released thing" not in section
    assert "archived elsewhere" not in section
    assert _unreleased_section("# Changelog\n\n## [0.4.8] - 2026-09-22\n") == ""


def test_the_budget_separates_a_notable_slice_from_a_fix_log() -> None:
    slice_ = "## [Unreleased]\n\n### Fixed\n" + "".join(f"- thing {i}\n" for i in range(8))
    assert _over_budget(slice_) == []
    log = "## [Unreleased]\n\n### Fixed\n" + "".join(f"- fix {i}\n" for i in range(200))
    problems = _over_budget(log)
    assert len(problems) == 2, problems
    # a long single bullet is prose, not a fix log; the line budget alone must not condemn it
    assert _over_budget("## [Unreleased]\n\n- " + "word " * 400 + "\n") == []


def test_the_changelog_gate_is_not_vacuous() -> None:
    text = _CHANGELOG.read_text(encoding="utf-8")
    section = _unreleased_section(text)
    assert section, "no Unreleased heading at line start, so the budget would read an empty section"
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    assert len(bullets) >= 5, f"only {len(bullets)} bullets: the section was emptied, not condensed"
    assert re.search(r"^## \[0\.4\.8\]", text, re.M), "the released sections went missing"


def test_the_unreleased_section_stays_within_budget() -> None:
    assert _over_budget(_CHANGELOG.read_text(encoding="utf-8")) == []


def test_the_archived_detail_is_named_and_reachable() -> None:
    section = _unreleased_section(_CHANGELOG.read_text(encoding="utf-8"))
    pointers = sorted(set(re.findall(r"docs/archive/[\w.-]+\.md", section)))
    assert pointers, "condensing without naming the archive would lose the detail"
    tracked = set(_tracked_files())
    for pointer in pointers:
        path = ROOT / pointer
        assert path.is_file(), f"{pointer} is named but does not exist"
        assert pointer in tracked, f"{pointer} is not tracked, so a clone would not have it"
        assert path.stat().st_size > len(section.encode("utf-8")), f"{pointer} holds less than it replaced"
