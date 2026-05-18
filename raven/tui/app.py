from __future__ import annotations

import time
from httpx import AsyncClient
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog, Static
from textual.containers import Container, Horizontal

API_BASE = "http://localhost:18888/api"
POLL_INTERVAL = 3.0
LOG_MAXLEN = 500


class LogWidget(RichLog):
    def __init__(self):
        super().__init__(highlight=True, markup=True, max_lines=200)
        self._log_buffer: set = set()

    def on_mount(self) -> None:
        self.set_interval(POLL_INTERVAL * 2, self._poll_logs)

    async def _poll_logs(self) -> None:
        try:
            async with AsyncClient() as client:
                resp = await client.get(f"{API_BASE}/logs?lines=50", timeout=5)
                if resp.status_code == 200:
                    logs = resp.json().get("logs", [])
                    for entry in logs:
                        line = entry.get("line", str(entry))
                        if line not in self._log_buffer:
                            self._log_buffer.add(line)
                            self.write(line)
        except Exception:
            pass


class DashboardScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Label("Raven AI Dashboard", classes="title")
            with Horizontal():
                yield Static("Channels: 0", id="channels", classes="stat")
                yield Static("Sessions: 0", id="sessions", classes="stat")
                yield Static("Uptime: --", id="uptime", classes="stat")
                yield Static("Model: --", id="model", classes="stat")
            yield LogWidget()
        yield Footer()

    def on_mount(self) -> None:
        self._start_time = time.time()
        self.set_interval(POLL_INTERVAL, self._poll_stats)

    def _format_uptime(self, seconds: float) -> str:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m:02d}m {s:02d}s"

    async def _poll_stats(self) -> None:
        try:
            async with AsyncClient() as client:
                resp = await client.get(f"{API_BASE}/health", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    self.query_one("#channels", Static).update(f"Channels: {data.get('channels', 0)}")
                    self.query_one("#sessions", Static).update(f"Sessions: {data.get('sessions', 0)}")
                    self.query_one("#model", Static).update(f"Model: {data.get('model', '--')}")
            self.query_one("#uptime", Static).update(f"Uptime: {self._format_uptime(time.time() - self._start_time)}")
        except Exception:
            self.query_one("#channels", Static).update("Channels: ?")


class RavenTUI(App):
    TITLE = "Raven AI"
    SUB_TITLE = "v0.4.0"

    SCREENS = {
        "dashboard": DashboardScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("dashboard")


def run() -> None:
    app = RavenTUI()
    app.run()
