from __future__ import annotations

import pytest

from raven.core.events import EventBus


async def test_publish_invokes_subscribers() -> None:
    bus = EventBus()
    received: list[dict[str, str]] = []

    async def handler(task_id: str) -> None:
        received.append({"task_id": task_id})

    bus.subscribe("task.completed", handler)
    await bus.publish("task.completed", task_id="t1", channel="telegram")
    assert received == [{"task_id": "t1"}]


async def test_publish_filters_unknown_kwargs() -> None:
    bus = EventBus()
    received: list[tuple[str, str]] = []

    async def handler(task_id: str, status: str) -> None:
        received.append((task_id, status))

    bus.subscribe("task.completed", handler)
    await bus.publish("task.completed", task_id="t1", status="completed", extra_key="ignored")
    assert received == [("t1", "completed")]


async def test_publish_without_subscribers_is_noop() -> None:
    bus = EventBus()
    await bus.publish("task.completed", task_id="t1")


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    count = {"n": 0}

    async def handler(**kwargs) -> None:
        count["n"] += 1

    bus.subscribe("monitor.alert", handler)
    await bus.publish("monitor.alert", monitor_id="m1")
    bus.unsubscribe("monitor.alert", handler)
    await bus.publish("monitor.alert", monitor_id="m1")
    assert count["n"] == 1


async def test_handler_error_does_not_break_bus() -> None:
    bus = EventBus()

    async def bad_handler(**kwargs) -> None:
        raise RuntimeError("boom")

    async def good_handler(**kwargs) -> None:
        pass

    bus.subscribe("monitor.alert", bad_handler)
    bus.subscribe("monitor.alert", good_handler)
    await bus.publish("monitor.alert", monitor_id="m1")
    assert bus.subscriber_count("monitor.alert") == 2


async def test_duplicate_subscribe_is_idempotent() -> None:
    bus = EventBus()

    async def handler(**kwargs) -> None:
        pass

    bus.subscribe("gateway.started", handler)
    bus.subscribe("gateway.started", handler)
    assert bus.subscriber_count("gateway.started") == 1
    assert bus.events == ["gateway.started"]


async def test_recent_records_events() -> None:
    bus = EventBus()
    await bus.publish("monitor.alert", monitor_id="m1")
    await bus.publish("task.completed", task_id="t1")
    await bus.publish("monitor.alert", monitor_id="m2")
    all_events = bus.recent()
    assert [e["event"] for e in all_events] == ["monitor.alert", "task.completed", "monitor.alert"]
    alerts = bus.recent(event="monitor.alert")
    assert [e["data"]["monitor_id"] for e in alerts] == ["m1", "m2"]
    assert bus.recent(limit=1)[0]["event"] == "monitor.alert"


async def test_history_size_is_bounded() -> None:
    bus = EventBus(history_size=2)
    for i in range(5):
        await bus.publish("task.completed", task_id=f"t{i}")
    assert len(bus.recent()) == 2
    assert bus.recent()[0]["data"]["task_id"] == "t3"


async def test_var_kwargs_handler_receives_all_data() -> None:
    bus = EventBus()
    received: list[dict[str, str]] = []

    async def handler(**data) -> None:
        received.append(dict(data))

    bus.subscribe("gateway.message_received", handler)
    await bus.publish("gateway.message_received", channel="telegram", user_id="u1")
    assert received == [{"channel": "telegram", "user_id": "u1"}]
