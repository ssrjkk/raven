from __future__ import annotations

import time

import pytest

from raven.core.canvas import CanvasComponent, CanvasManager, CanvasSession

# ---------------------------------------------------------------------------
# CanvasComponent
# ---------------------------------------------------------------------------


def test_component_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown component type"):
        CanvasComponent("spaceship")


def test_component_defaults() -> None:
    c = CanvasComponent("box")
    assert c.props == {}
    assert c.children == []
    assert c.ctype == "box"
    assert c.id.startswith("comp_")


def test_component_add_child_returns_self_and_nests() -> None:
    parent = CanvasComponent("columns")
    child = CanvasComponent("text", {"content": "hi"})
    assert parent.add_child(child) is parent
    assert parent.children == [child]


def test_component_to_dict_is_recursive() -> None:
    leaf = CanvasComponent("badge", {"label": "new"})
    root = CanvasComponent("card", {"title": "T"}, [leaf])
    d = root.to_dict()
    assert d["type"] == "card"
    assert d["props"] == {"title": "T"}
    assert d["id"] == root.id
    assert len(d["children"]) == 1
    assert d["children"][0]["type"] == "badge"
    assert d["children"][0]["children"] == []


# ---------------------------------------------------------------------------
# CanvasSession
# ---------------------------------------------------------------------------


def test_session_render_sets_root_and_touches_updated() -> None:
    s = CanvasSession("s1")
    old = s.updated_at
    s.updated_at = old - 10
    comp = CanvasComponent("box")
    s.render(comp)
    assert s.root is comp
    assert s.updated_at >= old


def test_session_update_props_finds_nested_and_merges() -> None:
    inner = CanvasComponent("input", {"value": "a"})
    root = CanvasComponent("columns", {}, [inner])
    s = CanvasSession("s2")
    s.render(root)
    s.update_props(inner.id, {"placeholder": "p", "value": "b"})
    assert inner.props == {"value": "b", "placeholder": "p"}


def test_session_update_props_on_root_itself() -> None:
    root = CanvasComponent("card", {"title": "old"})
    s = CanvasSession("s3")
    s.render(root)
    s.update_props(root.id, {"title": "new"})
    assert root.props["title"] == "new"


def test_session_update_props_noop_without_root() -> None:
    s = CanvasSession("s4")
    s.update_props("comp_missing", {"x": 1})
    assert s.root is None


def test_session_push_event_adds_timestamp() -> None:
    s = CanvasSession("s5")
    s.push_event({"kind": "click"})
    assert s.events[0]["kind"] == "click"
    assert "timestamp" in s.events[0]


def test_session_push_event_trims_to_100() -> None:
    s = CanvasSession("s6")
    for i in range(101):
        s.push_event({"n": i})
    assert len(s.events) == 100
    assert s.events[0]["n"] == 1


def test_session_to_dict_shape() -> None:
    s = CanvasSession("s7")
    empty = s.to_dict()
    assert empty["session_id"] == "s7"
    assert empty["root"] is None
    assert empty["events"] == []

    s.render(CanvasComponent("box"))
    for i in range(25):
        s.push_event({"n": i})
    d = s.to_dict()
    assert d["root"]["type"] == "box"
    assert len(d["events"]) == 20
    assert d["events"][0]["n"] == 5


# ---------------------------------------------------------------------------
# CanvasManager
# ---------------------------------------------------------------------------


def test_manager_create_get_delete() -> None:
    m = CanvasManager()
    s = m.create_session("a")
    assert m.get_session("a") is s
    m.delete_session("a")
    assert m.get_session("a") is None
    m.delete_session("a")  # missing is a no-op


def test_manager_render_existing_and_missing() -> None:
    m = CanvasManager()
    comp = CanvasComponent("box")
    s = m.create_session("a")
    assert m.render("a", comp) is s
    assert s.root is comp
    assert m.render("missing", comp) is None


def _root_with_input() -> tuple[CanvasManager, CanvasSession, CanvasComponent]:
    m = CanvasManager()
    s = m.create_session("a")
    inp = CanvasComponent("input", {"value": "old"})
    s.render(CanvasComponent("columns", {}, [inp]))
    return m, s, inp


def test_manager_handle_action_missing_session_returns_none() -> None:
    assert CanvasManager().handle_action("nope", "c", "click") is None


@pytest.mark.parametrize("action", ["click", "select", "toggle"])
def test_manager_handle_action_interaction(action: str) -> None:
    m, _s, inp = _root_with_input()
    assert m.handle_action("a", inp.id, action) == {"status": "handled", "action": action}


def test_manager_handle_action_change_updates_value() -> None:
    m, _s, inp = _root_with_input()
    result = m.handle_action("a", inp.id, "change", {"value": "new"})
    assert result == {"status": "updated", "action": "change"}
    assert inp.props["value"] == "new"


def test_manager_handle_action_change_without_value_key() -> None:
    m, _s, inp = _root_with_input()
    result = m.handle_action("a", inp.id, "change", {"other": 1})
    assert result == {"status": "updated", "action": "change"}
    assert inp.props["value"] == "old"


def test_manager_handle_action_change_component_not_found() -> None:
    m, _s, _inp = _root_with_input()
    result = m.handle_action("a", "comp_missing", "change", {"value": "x"})
    assert result == {"status": "updated", "action": "change"}


def test_manager_handle_action_change_without_root_falls_to_queued() -> None:
    m = CanvasManager()
    m.create_session("empty")
    assert m.handle_action("empty", "c", "change", {"value": "x"}) == {"status": "queued", "action": "change"}


def test_manager_handle_action_submit() -> None:
    m, _s, inp = _root_with_input()
    assert m.handle_action("a", inp.id, "submit", {"form": 1}) == {"status": "submitted", "data": {"form": 1}}
    assert m.handle_action("a", inp.id, "submit") == {"status": "submitted", "data": {}}


def test_manager_handle_action_unknown_queued() -> None:
    m, _s, inp = _root_with_input()
    assert m.handle_action("a", inp.id, "scroll") == {"status": "queued", "action": "scroll"}


def test_manager_handle_action_pushes_event() -> None:
    m, s, inp = _root_with_input()
    m.handle_action("a", inp.id, "click", {"x": 2})
    assert s.events[-1]["component_id"] == inp.id
    assert s.events[-1]["data"] == {"x": 2}


def test_manager_list_sessions_filters_active() -> None:
    m = CanvasManager()
    fresh = m.create_session("fresh")
    stale = m.create_session("stale")
    stale.updated_at = time.time() - 4000
    ids = {row["session_id"] for row in m.list_sessions()}
    assert ids == {"fresh"}
    row = m.list_sessions()[0]
    assert row["session_id"] == "fresh"
    assert row["age_seconds"] < 3600
    assert fresh.updated_at == row["updated_at"]


def test_manager_cleanup_removes_only_stale() -> None:
    m = CanvasManager()
    fresh = m.create_session("fresh")
    stale = m.create_session("stale")
    stale.updated_at = time.time() - 4000
    m.cleanup(max_age=3600)
    assert m.get_session("stale") is None
    assert m.get_session("fresh") is fresh


def test_manager_cleanup_noop_when_none_expired() -> None:
    m = CanvasManager()
    m.create_session("a")
    m.cleanup()
    assert m.get_session("a") is not None
