from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger

from raven.core.llm import LLMRouter
from raven.core.config import settings
from aios.runtime.adapter import RuntimeAdapter

router = APIRouter(prefix="/aios", tags=["ai-os-mvp"])


class AIRequest(BaseModel):
    prompt: str
    task: str = "code"
    model: str | None = None


class AIResponse(BaseModel):
    text: str
    model: str
    provider: str


class ExecRequest(BaseModel):
    command: str


class ExecResponse(BaseModel):
    output: str
    error: str | None = None


@router.post("/ai", response_model=AIResponse)
async def aios_gateway(req: AIRequest):
    llm = LLMRouter()
    provider_map = {"architecture": "anthropic", "fast": "openai"}
    provider_name = provider_map.get(req.task, "openrouter")
    model_name = req.model or settings.default_model

    try:
        response = await llm.complete(
            messages=[{"role": "user", "content": req.prompt}],
            model=model_name,
            provider=provider_name,
        )
        text = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.error("AI gateway request failed: {}", exc)
        text = f"AI request failed: {exc}"

    return AIResponse(text=text, model=model_name, provider=provider_name)


@router.post("/exec", response_model=ExecResponse)
async def aios_exec(req: ExecRequest):
    try:
        output = await RuntimeAdapter.run_command(req.command)
        return ExecResponse(output=output)
    except Exception as exc:
        logger.error("Exec failed: {}", exc)
        return ExecResponse(output="", error=str(exc))


@router.get("/health")
async def aios_health():
    return {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}
