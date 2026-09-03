"""orjson-based JSON serialisation, API-compatible with stdlib json.

Provides ~3-10x faster loads/dumps than stdlib json.
Usage: replace `import json` with `from raven.core._json import json`.
"""

from __future__ import annotations

import json as _stdlib_json
from typing import Any

import orjson

_SORT_KEYS = orjson.OPT_SORT_KEYS
_INDENT_2 = orjson.OPT_INDENT_2


class _Json:
    """Drop-in replacement for stdlib json module using orjson."""

    JSONDecodeError = orjson.JSONDecodeError

    @staticmethod
    def loads(s: str | bytes) -> Any:
        if isinstance(s, str):
            s = s.encode("utf-8")
        return orjson.loads(s)

    @staticmethod
    def dumps(obj: Any, **kwargs: Any) -> str:
        opts = 0
        if kwargs.pop("sort_keys", False):
            opts |= _SORT_KEYS
        indent = kwargs.pop("indent", None)
        if indent:
            opts |= _INDENT_2
        default = kwargs.pop("default", None)
        # orjson always serialises to UTF-8 (non-ASCII-escaped). It has no
        # ASCII-escaping option, so an explicit ensure_ascii=True is emulated
        # via stdlib json. Default (and ensure_ascii=False) uses orjson.
        ensure_ascii = kwargs.pop("ensure_ascii", False)
        if ensure_ascii is True:
            return _stdlib_json.dumps(obj, ensure_ascii=True, default=default)
        if kwargs:
            return _stdlib_json.dumps(obj, **kwargs)
        result = orjson.dumps(obj, default=default, option=opts or None)
        return result.decode("utf-8")


json = _Json()
