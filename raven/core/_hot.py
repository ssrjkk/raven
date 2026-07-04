from __future__ import annotations

from collections.abc import Callable
from typing import Any

_HAS_NUMBA = False
try:
    from numba import njit
    from numba import prange as _prange

    _HAS_NUMBA = True
except ImportError:

    def njit(*args: Any, **kwargs: Any) -> Callable[..., Any]:
        if args and callable(args[0]):
            return args[0]  # type: ignore[no-any-return]
        return lambda f: f

    _prange = range


if _HAS_NUMBA:

    @njit(cache=True)  # type: ignore[untyped-decorator]
    def fast_replace(s: str, old: str, new: str) -> str:
        return s.replace(old, new)

    @njit(cache=True)  # type: ignore[untyped-decorator]
    def count_tokens(text: str) -> int:
        words = 1
        for ch in text:
            if ch == " ":
                words += 1
        return words

else:

    def fast_replace(s: str, old: str, new: str) -> str:
        return s.replace(old, new)

    def count_tokens(text: str) -> int:
        return len(text.split())


__all__ = ["fast_replace", "count_tokens", "njit", "_prange", "_HAS_NUMBA"]
