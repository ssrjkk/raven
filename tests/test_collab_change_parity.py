"""One change geometry, checked in both languages.

`tests/fixtures/collab_change_cases.json` is asserted here against `CollaborationSession.apply_change`
and in `web/src/lib/collab.test.ts` against `applyChange`. A range the two sides resolve differently
leaves the editor showing a document the gateway does not have, so every value in that table is
produced by the Python implementation and re-produced by the client -- none of it is typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from raven.unique.collaboration import CollaborationSession, TextChange

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / "tests" / "fixtures" / "collab_change_cases.json").read_text(encoding="utf-8"))
CHANGE_FIELDS = ("user_id", "file", "start_line", "start_col", "end_line", "end_col", "old_text", "new_text")


def _change(body: dict[str, Any]) -> TextChange:
    return TextChange(**{name: body[name] for name in CHANGE_FIELDS})


def _session(content: str, file_path: str = "sample.py") -> CollaborationSession:
    session = CollaborationSession(session_id="parity", file_path=file_path)
    session.document.content = content
    return session


class _YTextStub:
    """What `_apply_change_crdt` needs of a y-py `YText`: code-point indexing, insert, delete, str.

    y-py is not installed everywhere this suite runs, and the CRDT branch is the one that used to
    disagree with the fallback about a reversed range. Without a stand-in, the two paths are only
    compared on the installs that happen to have the library.
    """

    def __init__(self, content: str) -> None:
        self._points = list(content)

    def insert(self, index: int, text: str) -> None:
        self._points[index:index] = list(text)

    def delete(self, index: int, length: int) -> None:
        del self._points[index : index + length]

    def __str__(self) -> str:
        return "".join(self._points)


CASE_IDS = [case["name"] for case in TABLE["cases"]]
ROUNDTRIP_IDS = [row["name"] for row in TABLE["roundtrip"]]


@pytest.mark.parametrize("case", TABLE["cases"], ids=CASE_IDS)
def test_the_gateway_applies_exactly_what_the_table_records(case: dict[str, Any]) -> None:
    session = _session(case["content"])
    version_before = session.document.version

    applied = session.apply_change(_change(case["change"]))

    assert applied is case["applies"], case["name"]
    assert session.document.content == case["expected"], case["name"]
    assert session.document.version == version_before + (1 if applied else 0)


@pytest.mark.parametrize("case", TABLE["cases"], ids=CASE_IDS)
def test_the_crdt_path_and_the_fallback_agree(case: dict[str, Any]) -> None:
    """The same change has to land the same way with or without y-py installed."""
    plain = _session(case["content"])
    fallback_result = plain._apply_change_fallback(_change(case["change"]))
    fallback_content = plain.document.content

    crdt = _session(case["content"])
    crdt._ytext = _YTextStub(case["content"])
    crdt_result = crdt._apply_change_crdt(_change(case["change"]))

    assert crdt_result is fallback_result, case["name"]
    assert crdt.document.content == fallback_content, case["name"]
    if not crdt_result:
        assert crdt.document.content == case["content"], case["name"]


@pytest.mark.parametrize("row", TABLE["roundtrip"], ids=ROUNDTRIP_IDS)
def test_every_edit_in_the_table_is_reversible_by_the_gateway(row: dict[str, Any]) -> None:
    """A client's diff, applied server-side, has to reproduce exactly what the client typed."""
    session = _session(row["prev"])

    assert session.apply_change(_change(row["change"])) is True
    assert session.document.content == row["next"]


def test_the_table_covers_the_ranges_the_two_sides_used_to_disagree_about() -> None:
    """Category coverage, measured from the rows themselves rather than asserted as a count.

    Losing a category would quietly retire one of the divergences this table pins, and a row count
    alone would not notice.
    """
    cases = TABLE["cases"]
    roundtrip = TABLE["roundtrip"]

    assert any(case["applies"] is False for case in cases), "no refused range left"
    assert any(case["change"]["end_line"] > case["change"]["start_line"] and case["applies"] for case in cases), (
        "no multi-line range left"
    )
    assert any(case["change"]["start_col"] > case["change"]["end_col"] for case in cases), "no reversed range left"
    assert any(
        case["change"]["start_col"] > len(case["content"].split("\n")[case["change"]["start_line"]])
        for case in cases
        if case["applies"]
    ), "no column past the line end left"
    assert any(any(ord(char) > 0xFFFF for char in row["prev"] + row["next"]) for row in roundtrip), (
        "no astral character left"
    )
    assert any(row["prev"] == "" for row in roundtrip), "no edit into an empty document left"
