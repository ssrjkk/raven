from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from aios.runtime.adapter import RuntimeAdapter
from ravencode.agents.orchestrator import Orchestrator
from ravencode.api.client import AIOSClient

router = APIRouter(prefix="/aios", tags=["ai-os-mvp"])
_orch = Orchestrator()
_client = AIOSClient()


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
    result = await _client.ask(prompt=req.prompt, task=req.task, model=req.model)
    return AIResponse(text=result.text, model=result.model, provider=result.provider)


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
