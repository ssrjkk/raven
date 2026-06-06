from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from loguru import logger

_COMPONENT_TYPES = frozenset(
    {
        "box",
        "text",
        "button",
        "input",
        "select",
        "table",
        "chart",
        "card",
        "list",
        "image",
        "progress",
        "spacer",
        "columns",
        "tabs",
        "icon",
        "badge",
        "code",
        "link",
        "chip",
    }
)


class CanvasComponent:
    def __init__(self, ctype: str, props: dict[str, Any] | None = None, children: list[CanvasComponent] | None = None):
        assert ctype in _COMPONENT_TYPES, f"Unknown component type: {ctype}"
        self.id = f"comp_{uuid4().hex[:12]}"
        self.ctype = ctype
        self.props = props or {}
        self.children = children or []

    def add_child(self, child: CanvasComponent):
        self.children.append(child)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.ctype,
            "props": self.props,
            "children": [c.to_dict() for c in self.children],
        }


def Box(props: dict[str, Any] | None = None, *children: CanvasComponent) -> CanvasComponent:
    c = CanvasComponent("box", props)
    for ch in children:
        c.add_child(ch)
    return c


def Text(content: str, **props) -> CanvasComponent:
    p = {"content": content, **props}
    return CanvasComponent("text", p)


def Button(label: str, action: str, **props) -> CanvasComponent:
    p = {"label": label, "action": action, **props}
    return CanvasComponent("button", p)


def Input(name: str, label: str = "", placeholder: str = "", **props) -> CanvasComponent:
    p = {"name": name, "label": label, "placeholder": placeholder, **props}
    return CanvasComponent("input", p)


def Select(name: str, options: list[dict[str, Any]], label: str = "", **props) -> CanvasComponent:
    p = {"name": name, "options": options, "label": label, **props}
    return CanvasComponent("select", p)


def Table(headers: list[str], rows: list[list[str]], **props) -> CanvasComponent:
    p = {"headers": headers, "rows": rows, **props}
    return CanvasComponent("table", p)


def Card(title: str, *children: CanvasComponent, **props) -> CanvasComponent:
    c = CanvasComponent("card", {"title": title, **props})
    for ch in children:
        c.add_child(ch)
    return c


def Chart(data: list[dict[str, Any]], chart_type: str = "bar", **props) -> CanvasComponent:
    p = {"data": data, "chartType": chart_type, **props}
    return CanvasComponent("chart", p)


def Code(content: str, language: str = "", **props) -> CanvasComponent:
    p = {"content": content, "language": language, **props}
    return CanvasComponent("code", p)


def Columns(*children: CanvasComponent, **props) -> CanvasComponent:
    c = CanvasComponent("columns", props)
    for ch in children:
        c.add_child(ch)
    return c


def Tabs(tabs: list[dict[str, Any]], **props) -> CanvasComponent:
    p = {"tabs": tabs, **props}
    return CanvasComponent("tabs", p)


def Badge(text: str, variant: str = "default", **props) -> CanvasComponent:
    p = {"text": text, "variant": variant, **props}
    return CanvasComponent("badge", p)


def Image(url: str, **props) -> CanvasComponent:
    p = {"url": url, **props}
    return CanvasComponent("image", p)


def Link(href: str, text: str, **props) -> CanvasComponent:
    p = {"href": href, "text": text, **props}
    return CanvasComponent("link", p)


def Progress(value: float, max_val: float = 1.0, **props) -> CanvasComponent:
    p = {"value": value, "max": max_val, **props}
    return CanvasComponent("progress", p)


def List(items: list[dict[str, Any]], **props) -> CanvasComponent:
    p = {"items": items, **props}
    return CanvasComponent("list", p)


class CanvasSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.root: CanvasComponent | None = None
        self.events: list[dict[str, Any]] = []
        self.created_at = time.time()
        self.updated_at = time.time()

    def render(self, component: CanvasComponent):
        self.root = component
        self.updated_at = time.time()

    def update_props(self, component_id: str, props: dict[str, Any]):
        def _walk(c: CanvasComponent) -> bool:
            if c.id == component_id:
                c.props.update(props)
                return True
            for child in c.children:
                if _walk(child):
                    return True
            return False

        if self.root:
            _walk(self.root)
        self.updated_at = time.time()

    def push_event(self, event: dict[str, Any]):
        self.events.append({**event, "timestamp": time.time()})
        if len(self.events) > 100:
            self.events.pop(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "root": self.root.to_dict() if self.root else None,
            "events": self.events[-20:],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class CanvasManager:
    def __init__(self):
        self._sessions: dict[str, CanvasSession] = {}

    def create_session(self, session_id: str) -> CanvasSession:
        session = CanvasSession(session_id)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> CanvasSession | None:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def render(self, session_id: str, component: CanvasComponent):
        session = self._sessions.get(session_id)
        if session:
            session.render(component)
        return session

    def handle_action(
        self, session_id: str, component_id: str, action: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.push_event({"component_id": component_id, "action": action, "data": data or {}})
        if hasattr(session, "_action_handler"):
            return session._action_handler(component_id, action, data or {})  # type: ignore[no-any-return]
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        now = time.time()
        active = []
        for sid, s in self._sessions.items():
            age = now - s.updated_at
            if age < 3600:
                active.append({"session_id": sid, "updated_at": s.updated_at, "age_seconds": age})
        return active

    def cleanup(self, max_age: float = 3600):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.updated_at > max_age]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("Canvas cleanup: removed {} stale sessions", len(expired))


canvas_manager = CanvasManager()
