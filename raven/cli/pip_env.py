# ruff: noqa: RUF002 (intentional Cyrillic in Russian comments)
"""Доступен ли установщик пакетов в среде, где запущен CLI.

Docker-образ собирается без него: он нужен только на стадии сборки, а в готовом
образе тащит вендоренные копии зависимостей, которые сканер затем приписывает
приложению (urllib3 внутри pip — ровно тот случай).
"""

from __future__ import annotations

import importlib.util


def pip_available() -> bool:
    return importlib.util.find_spec("pip") is not None


MISSING_PIP = (
    "pip is not installed in this environment (the container image ships without it); update by deploying a newer image"
)
