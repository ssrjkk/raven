from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger


class SagaStepStatus:
    PENDING = "pending"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


class SagaError(Exception):
    def __init__(self, message: str, step: str, cause: Exception | None = None):
        self.step = step
        self.cause = cause
        super().__init__(f"Saga failed at step '{step}': {message}")


class Saga:
    """SAGA choreography coordinator.

    Each step has a forward action and a compensation action.
    If any forward action fails, all completed steps are compensated in reverse order.
    Used for distributed transactions across microservices.
    """

    def __init__(self, saga_id: str | None = None, timeout: float = 60.0):
        self.saga_id = saga_id or str(uuid.uuid4())
        self._steps: list[SagaStep] = []
        self._results: dict[str, Any] = {}
        self._timeout = timeout

    def add_step(self, name: str, action: Callable[[], Awaitable[Any]], compensate: Callable[[], Awaitable[None]]):
        self._steps.append(SagaStep(name=name, action=action, compensate=compensate))

    async def execute(self) -> dict[str, Any]:
        completed: list[SagaStep] = []

        try:
            async with asyncio.timeout(self._timeout):
                for step in self._steps:
                    step.status = SagaStepStatus.PENDING
                    try:
                        result = await step.action()
                        step.status = SagaStepStatus.COMPLETED
                        self._results[step.name] = result
                        completed.append(step)
                        logger.info("[saga/{}] step '{}' completed", self.saga_id, step.name)
                    except Exception as e:
                        step.status = SagaStepStatus.FAILED
                        step.error = str(e)
                        logger.error("[saga/{}] step '{}' failed: {}", self.saga_id, step.name, e)
                        await self._compensate(completed)
                        raise SagaError(f"Step '{step.name}' failed: {e}", step.name, e) from e

        except TimeoutError:
            logger.error("[saga/{}] timeout after {}s", self.saga_id, self._timeout)
            await self._compensate(completed)
            raise SagaError("Saga timeout", "timeout") from None

        return self._results

    async def _compensate(self, completed: list[SagaStep]):
        for step in reversed(completed):
            try:
                step.status = SagaStepStatus.COMPENSATING
                await step.compensate()
                step.status = SagaStepStatus.COMPENSATED
                logger.info("[saga/{}] compensated step '{}'", self.saga_id, step.name)
            except Exception as e:
                logger.error("[saga/{}] compensation failed for step '{}': {}", self.saga_id, step.name, e)


class SagaStep:
    def __init__(self, name: str, action: Callable[[], Awaitable[Any]], compensate: Callable[[], Awaitable[None]]):
        self.name = name
        self.action = action
        self.compensate = compensate
        self.status: str = SagaStepStatus.PENDING
        self.error: str | None = None


# ── Example: User Registration Saga ────────────────────────────


class UserRegistrationSaga(Saga):
    """Example SAGA: register user → create default monitors → send welcome.

    If any step fails, compensate completed steps:
    1. Delete user account (compensate: nothing — auth handles rollback)
    2. Create default monitors (compensate: delete monitors)
    3. Send welcome notification (compensate: no-op)
    """

    def __init__(self, user_id: str, username: str):
        super().__init__(saga_id=f"user-reg-{user_id}")
        self.user_id = user_id
        self.username = username

    @classmethod
    async def run(cls, user_id: str, username: str, email: str = "") -> dict[str, Any]:
        saga = cls(user_id, username)
        saga._build_steps(email)
        return await saga.execute()

    def _build_steps(self, email: str):
        async def _notify():
            logger.info("Welcome notification sent to {} ({})", self.username, email)

        async def _noop_compensate():
            logger.info("[saga/{}] no-op compensation for send_welcome (irreversible)", self.saga_id)

        async def _create_monitors():
            logger.info("Creating default monitors for {}", self.user_id)

        async def _delete_monitors():
            logger.info("Deleted default monitors for {}", self.user_id)

        self.add_step("send_welcome", _notify, _noop_compensate)
        self.add_step("create_default_monitors", _create_monitors, _delete_monitors)
