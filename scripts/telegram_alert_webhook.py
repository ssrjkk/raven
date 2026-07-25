#!/usr/bin/env python3
"""Telegram alerting webhook for Prometheus AlertManager.

Usage: python scripts/telegram_alert_webhook.py
Starts a Flask server on :9094. Configure AlertManager:
  receivers:
  - name: telegram
    webhook_configs:
    - url: http://telegram-alerter:9094/alert
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT = int(os.environ.get("PORT", "9094"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("telegram-alerter")


class AlertHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body)

        for alert in data.get("alerts", []):
            status = alert.get("status", "unknown")
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            message = (
                f"🚨 *{status.upper()}*: {annotations.get('summary', 'No summary')}\n"
                f"Service: {labels.get('service', 'unknown')}\n"
                f"Severity: {labels.get('severity', 'unknown')}\n"
                f"Description: {annotations.get('description', '')}\n"
                f"{{% if status == 'firing' %}}🔥 Active{{% else %}}✅ Resolved{{% endif %}}"
            )
            self._send_telegram(message)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def _send_telegram(self, text: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return
        try:
            httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            log.info("Alert sent to Telegram: %s", text[:80])
        except Exception:
            log.exception("Failed to send Telegram alert")

    def log_message(self, format, *args):
        log.info(format, *args)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), AlertHandler)
    log.info("Telegram alert webhook listening on :%d", PORT)
    server.serve_forever()
