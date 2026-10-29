from __future__ import annotations

import os
from pathlib import Path

import pytest

TINY_LLAMA = "hf-internal-testing/tiny-random-LlamaForCausalLM"


def ml_enabled() -> bool:
    return os.environ.get("RAVEN_ML_SMOKE") == "1"


@pytest.fixture(scope="session")
def trained_adapter(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """One tiny LoRA run shared by the whole ml suite: train once, then reuse the directory.

    Nothing heavy is imported at module level: the main CI matrix has no torch, and a top-level
    import here would turn a skip into a collection error.
    """
    if not ml_enabled():
        pytest.skip("set RAVEN_ML_SMOKE=1 to run the training suite")

    from raven.unique.fine_tuning import (
        ConversationExample,
        DatasetBuilder,
        DatasetConfig,
        FineTuningPipeline,
        TrainingConfig,
    )

    out = tmp_path_factory.mktemp("finetune")
    config = TrainingConfig(
        output_dir=str(out / "ckpt"),
        model_type="llama",
        model_name_or_path=TINY_LLAMA,
        num_epochs=1,
        batch_size=2,
        gradient_accumulation_steps=1,
        learning_rate=1e-3,
        warmup_steps=0,
        logging_steps=1,
        save_steps=10,
        eval_steps=10,
        use_lora=True,
        use_qlora=False,
        seed=0,
    )
    pipeline = FineTuningPipeline(config)
    pipeline.load_model()

    builder = DatasetBuilder(DatasetConfig(max_length=32, test_split=0.25))
    for turn in range(4):
        builder.add_conversation(
            ConversationExample(
                messages=[
                    {"role": "user", "content": f"count to {turn}"},
                    {"role": "assistant", "content": f"counting: {turn}"},
                ],
                consented=True,
            )
        )
    split = builder.build_dataset()
    tokenizer = pipeline.tokenizer
    assert tokenizer is not None
    train_ds = builder.tokenize_dataset(split["train"], tokenizer)

    pipeline.train(train_ds)
    return {"base": TINY_LLAMA, "adapter": out / "ckpt" / "final", "config": config, "out": out}


def adapter_dir(trained_adapter: dict[str, object]) -> Path:
    path = trained_adapter["adapter"]
    assert isinstance(path, Path)
    return path
