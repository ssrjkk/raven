from raven.core.monitor.engine import MonitorEngine
from raven.monitors.http import check_http
from raven.monitors.price import check_price
from raven.monitors.rss import check_rss
from raven.monitors.file import check_file
from raven.monitors.process import check_process


def register_all_monitors(engine: MonitorEngine) -> None:
    engine.register_handler("http", check_http)
    engine.register_handler("price", check_price)
    engine.register_handler("rss", check_rss)
    engine.register_handler("file", check_file)
    engine.register_handler("process", check_process)
