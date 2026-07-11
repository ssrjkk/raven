from __future__ import annotations

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.fine_tuning import DatasetBuilder, FineTuningPipeline

_pipeline: FineTuningPipeline | None = None
_builder: DatasetBuilder | None = None


def _get_pipeline() -> FineTuningPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = FineTuningPipeline()
    return _pipeline


def _get_builder() -> DatasetBuilder:
    global _builder
    if _builder is None:
        _builder = DatasetBuilder()
    return _builder


async def finetune_dataset_stats() -> str:
    builder = _get_builder()
    stats = builder.stats()
    return (
        f"Dataset Builder Statistics\n"
        f"- Conversations: {stats['conversations']}\n"
        f"- Code samples: {stats['code_samples']}\n"
        f"- Max length: {stats['config']['max_length']}\n"
        f"- Format: {stats['config']['format']}"
    )


async def finetune_add_conversation(system_prompt: str = "", messages_json: str = "") -> str:
    builder = _get_builder()
    from raven.unique.fine_tuning import ConversationExample
    try:
        import json
        messages = json.loads(messages_json) if messages_json else []
    except json.JSONDecodeError as e:
        return f"[error] Invalid JSON for messages: {e}"
    conv = ConversationExample(messages=messages, system_prompt=system_prompt)
    builder.add_conversation(conv)
    return f"Conversation added ({len(messages)} messages). Total: {builder.stats()['conversations']}"


async def finetune_add_code(code: str, language: str = "", description: str = "") -> str:
    builder = _get_builder()
    from raven.unique.fine_tuning import CodeExample
    builder.add_code(CodeExample(code=code, language=language, description=description))
    return f"Code sample added ({language}, {len(code)} chars). Total: {builder.stats()['code_samples']}"


async def finetune_load_model(model_type: str = "llama", use_lora: bool = True, use_qlora: bool = False) -> str:
    pipeline = _get_pipeline()
    pipeline.config.model_type = model_type
    pipeline.config.use_lora = use_lora
    pipeline.config.use_qlora = use_qlora
    try:
        pipeline.load_model()
        info = pipeline.get_model_info()
        return (
            f"Model loaded: {info['model_name']}\n"
            f"- Type: {info['model_type']}\n"
            f"- Trainable params: {info['trainable_params']:,}\n"
            f"- Total params: {info['total_params']:,}"
        )
    except Exception as e:
        logger.error("Model load failed: {}", e)
        return f"[error] Failed to load model: {e}"


async def finetune_start_training(epochs: int = 3, learning_rate: float = 2e-4, batch_size: int = 4) -> str:
    pipeline = _get_pipeline()
    builder = _get_builder()
    pipeline.config.num_epochs = epochs
    pipeline.config.learning_rate = learning_rate
    pipeline.config.batch_size = batch_size
    try:
        dataset = builder.build_dataset()
        tokenized = builder.tokenize_dataset(dataset["train"], pipeline._tokenizer)
        eval_tokenized = builder.tokenize_dataset(dataset["test"], pipeline._tokenizer) if len(dataset["test"]) > 0 else None
    except RuntimeError as e:
        return f"[error] Dataset error: {e}"
    except Exception as e:
        return f"[error] Build dataset failed: {e}"
    try:
        metrics = pipeline.train(tokenized, eval_tokenized)
        return (
            f"Training completed:\n"
            f"- Loss: {metrics.get('train_loss', 0):.4f}\n"
            f"- Steps: {metrics.get('global_step', 0)}\n"
            f"- Epochs: {metrics.get('epoch', 0)}\n"
            f"- Eval loss: {metrics.get('eval_loss', 'N/A')}\n"
            f"- Perplexity: {metrics.get('eval_perplexity', 'N/A')}"
        )
    except Exception as e:
        logger.error("Training failed: {}", e)
        return f"[error] Training failed: {e}"


async def finetune_model_info() -> str:
    pipeline = _get_pipeline()
    info = pipeline.get_model_info()
    return (
        f"Model: {info['model_name']}\n"
        f"Type: {info['model_type']}\n"
        f"Trainable params: {info['trainable_params']:,}\n"
        f"Total params: {info['total_params']:,}\n"
        f"Checkpoints: {info['checkpoints']}"
    )


async def finetune_list_checkpoints() -> str:
    pipeline = _get_pipeline()
    cps = pipeline.list_checkpoints()
    if not cps:
        return "[info] No checkpoints saved."
    lines = [f"Checkpoints ({len(cps)}):"]
    for cp in cps:
        lines.append(f"  - step={cp.step}, epoch={cp.epoch}, path={cp.path}")
    return "\n".join(lines)


def register_finetune_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="finetune_dataset_stats",
        description="Get statistics about the fine-tuning dataset builder",
        parameters={},
        handler=finetune_dataset_stats,
        category="finetune",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="finetune_add_conversation",
        description="Add a conversation example to the fine-tuning dataset",
        parameters={
            "system_prompt": {"type": "string", "description": "System prompt", "required": False},
            "messages_json": {"type": "string", "description": "JSON array of {role, content} messages", "required": False},
        },
        handler=finetune_add_conversation,
        category="finetune",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="finetune_add_code",
        description="Add a code sample to the fine-tuning dataset",
        parameters={
            "code": {"type": "string", "description": "Source code", "required": True},
            "language": {"type": "string", "description": "Programming language", "required": False},
            "description": {"type": "string", "description": "Description of the code", "required": False},
        },
        handler=finetune_add_code,
        category="finetune",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="finetune_load_model",
        description="Load a base model for fine-tuning (requires torch, transformers, peft)",
        parameters={
            "model_type": {"type": "string", "description": "Model type (llama, mistral, falcon, phi, qwen)", "required": False},
            "use_lora": {"type": "boolean", "description": "Apply LoRA (default true)", "required": False},
            "use_qlora": {"type": "boolean", "description": "Use QLoRA quantization (default false)", "required": False},
        },
        handler=finetune_load_model,
        category="finetune",
        timeout=300,
    ))
    registry.register(ToolSpec(
        name="finetune_start_training",
        description="Start fine-tuning training with the accumulated dataset",
        parameters={
            "epochs": {"type": "integer", "description": "Number of epochs (default 3)", "required": False},
            "learning_rate": {"type": "number", "description": "Learning rate (default 2e-4)", "required": False},
            "batch_size": {"type": "integer", "description": "Batch size per device (default 4)", "required": False},
        },
        handler=finetune_start_training,
        category="finetune",
        timeout=3600,
    ))
    registry.register(ToolSpec(
        name="finetune_model_info",
        description="Get information about the loaded fine-tuning model",
        parameters={},
        handler=finetune_model_info,
        category="finetune",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="finetune_list_checkpoints",
        description="List saved fine-tuning checkpoints",
        parameters={},
        handler=finetune_list_checkpoints,
        category="finetune",
        timeout=10,
    ))
