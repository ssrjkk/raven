from raven.core.monitor.engine import MonitorEngine
from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType


def register_all_monitors(engine: MonitorEngine):
    examples = [
        {
            "name": "Raven AI Status",
            "type": MonitorType.HTTP,
            "target": "https://status.raven.ai",
            "interval_seconds": 300,
            "status": MonitorStatus.ACTIVE,
        },
    ]
    existing = engine.list_monitors()
    existing_names = {m.name for m in existing}
    for cfg in examples:
        if cfg["name"] not in existing_names:
            m = Monitor(
                name=cfg["name"],
                type=cfg["type"],
                target=cfg["target"],
                interval_seconds=cfg["interval_seconds"],
                status=cfg["status"],
            )
            engine.add_monitor(m)
