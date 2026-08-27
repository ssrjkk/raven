from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.unique.fine_tuning import DatasetBuilder, FineTuningPipeline

_builder = DatasetBuilder()
_pipeline = FineTuningPipeline()


class AddConversationRequest(BaseModel):
    system_prompt: str = ""
    messages_json: str = ""


class AddCodeRequest(BaseModel):
    code: str
    language: str = ""
    description: str = ""


class LoadModelRequest(BaseModel):
    model_type: str = "llama"
    use_lora: bool = True
    use_qlora: bool = False


class StartTrainingRequest(BaseModel):
    epochs: int = 3
    learning_rate: float = 2e-4
    batch_size: int = 4


def create_finetune_router() -> APIRouter:
    router = APIRouter(prefix="/api/finetune", tags=["finetune"])

    @router.get("/dataset/stats")
    def dataset_stats():
        return _builder.stats()

    @router.post("/dataset/conversation")
    def add_conversation(req: AddConversationRequest):
        from raven.unique.fine_tuning import ConversationExample

        try:
            import json

            messages = json.loads(req.messages_json) if req.messages_json else []
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid messages JSON: {e}") from e
        conv = ConversationExample(messages=messages, system_prompt=req.system_prompt)
        _builder.add_conversation(conv)
        return {"success": True, "total": _builder.stats()["conversations"]}

    @router.post("/dataset/code")
    def add_code(req: AddCodeRequest):
        from raven.unique.fine_tuning import CodeExample

        _builder.add_code(CodeExample(code=req.code, language=req.language, description=req.description))
        return {"success": True, "total": _builder.stats()["code_samples"]}

    @router.post("/model/load")
    def load_model(req: LoadModelRequest):
        _pipeline.config.model_type = req.model_type
        _pipeline.config.use_lora = req.use_lora
        _pipeline.config.use_qlora = req.use_qlora
        try:
            _pipeline.load_model()
            return _pipeline.get_model_info()
        except Exception as e:
            logger.error("Model load failed: {}", e)
            raise internal_error(e) from e

    @router.post("/train")
    def start_training(req: StartTrainingRequest):
        _pipeline.config.num_epochs = req.epochs
        _pipeline.config.learning_rate = req.learning_rate
        _pipeline.config.batch_size = req.batch_size
        try:
            dataset = _builder.build_dataset()
        except RuntimeError as e:
            raise HTTPException(400, f"Build failed: {type(e).__name__}") from e
        except Exception as e:
            raise internal_error(e) from e
        try:
            tokenized = _builder.tokenize_dataset(dataset["train"], _pipeline._tokenizer)
            eval_tokenized = (
                _builder.tokenize_dataset(dataset["test"], _pipeline._tokenizer) if len(dataset["test"]) > 0 else None
            )
        except Exception as e:
            raise internal_error(e) from e
        try:
            return _pipeline.train(tokenized, eval_tokenized)
        except Exception as e:
            logger.error("Training failed: {}", e)
            raise internal_error(e) from e

    @router.get("/model/info")
    def model_info():
        return _pipeline.get_model_info()

    @router.get("/checkpoints")
    def list_checkpoints():
        cps = _pipeline.list_checkpoints()
        return {"checkpoints": [{"step": cp.step, "epoch": cp.epoch, "path": str(cp.path)} for cp in cps]}

    return router
