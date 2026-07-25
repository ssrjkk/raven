from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raven.core.cache.rate_limiter import RateLimiterProtocol

_ESTIMATED_TOKENS_PER_CHAR = 0.25


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) * _ESTIMATED_TOKENS_PER_CHAR))


class TokenBudgetTracker:
    def __init__(self, limiter: RateLimiterProtocol | None = None) -> None:
        if limiter is None:
            from raven.core.cache.rate_limiter import InMemoryRateLimiter

            self._limiter: RateLimiterProtocol = InMemoryRateLimiter()
        else:
            self._limiter = limiter

    async def check_budget(self, user_id: str, input_tokens: int, output_tokens: int, budget: int, window: int) -> bool:
        return await self._limiter.is_allowed_weighted(
            f"token_budget:{user_id}", input_tokens + output_tokens, budget, window
        )

    async def record_usage(self, user_id: str, tokens: int, budget: int, window: int) -> bool:
        return await self._limiter.is_allowed_weighted(
            f"token_budget:{user_id}", tokens, budget, window
        )
