"""
Bridge between Raven FastAPI backend and the AI-OS-MVP Fastify Gateway.

Exposes Raven's agent capabilities as a Fastify-compatible JSON API
so the Next.js IDE and Tauri desktop can consume them.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from raven.core.agent.agent import Agent
from raven.core.llm import LLMRouter

router = APIRouter(prefix="/aios", tags=["ai-os-mvp"])


class AIRequest(BaseModel):
    prompt: str
    task: str = "code"
    model: str | None = None
    context: list[str] | None = None


class AIResponse(BaseModel):
    text: str
    model: str
    provider: str


@router.post("/ai", response_model=AIResponse)
async def aios_gateway(req: AIRequest):
    """AI Gateway endpoint — routes to Raven's LLM router."""
    llm = LLMRouter()
    provider, model = llm.resolve(req.task, req.model)

    agent = Agent(model=model, provider=provider)
    result = await agent.run(req.prompt)

    return AIResponse(
        text=result,
        model=model,
        provider=provider,
    )


@router.get("/health")
async def aios_health():
    """Health check for AI-OS-MVP bridge."""
    return {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}
