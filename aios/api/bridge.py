"""
Bridge between Raven FastAPI backend and the AI-OS-MVP Fastify Gateway.

Exposes Raven's agent capabilities as a JSON API for the web IDE and desktop.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from raven.core.llm import LLMRouter
from raven.core.config import settings

router = APIRouter(prefix="/aios", tags=["ai-os-mvp"])


class AIRequest(BaseModel):
    prompt: str
    task: str = "code"
    model: str | None = None


class AIResponse(BaseModel):
    text: str
    model: str
    provider: str


@router.post("/ai", response_model=AIResponse)
async def aios_gateway(req: AIRequest):
    """AI Gateway endpoint — routes to Raven's LLM."""
    llm = LLMRouter()
    provider_name = "openrouter"

    if req.task == "architecture":
        provider_name = "anthropic"
    elif req.task == "fast":
        provider_name = "openai"

    model_name = req.model or settings.default_model

    response = await llm.complete(
        messages=[{"role": "user", "content": req.prompt}],
        model=model_name,
        provider=provider_name,
    )

    return AIResponse(
        text=response.content if hasattr(response, 'content') else str(response),
        model=model_name,
        provider=provider_name,
    )


@router.get("/health")
async def aios_health():
    return {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}
