from __future__ import annotations

from fastapi import HTTPException

from raven.core.api_errors import internal_error


def test_internal_error_returns_500_with_exception_type() -> None:
    exc = internal_error(ValueError("secret detail"))
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 500
    assert exc.detail == "Internal error: ValueError"
    assert "secret detail" not in exc.detail
