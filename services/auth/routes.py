from __future__ import annotations

from fastapi import APIRouter

from .store import AuthStore
from services.observability_sdk import get_correlation_id

router = APIRouter(prefix="/api/v1/auth")
