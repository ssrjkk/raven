"""A real fine-tuning run, end to end, on a model small enough for a CPU runner.

Until this file existed the 660 lines of `raven/unique/fine_tuning.py` had never executed anywhere:
torch/transformers/peft/datasets are an optional extra that no CI job installed, and the tests around
them asserted the "dependency missing" branch (`test_load_model_raises_without_deps`) or patched
`load_model` out. So the module could not have been broken and still reported green.

This test skips when it is not asked for, and fails when it is asked for but cannot run: the CI
`ml` job sets RAVEN_ML_SMOKE=1, and there a missing wheel or a missing model is an error, not a skip.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.ml

if os.environ.get("RAVEN_ML_SMOKE") != "1":
    pytest.skip("training smoke test runs in the CI ml job (RAVEN_ML_SMOKE=1)", allow_module_level=True)

import torch  # noqa: E402  (intentional: past the skip, an ImportError must surface)
from peft import PeftModel  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

from raven.unique.fine_tuning import (  # noqa: E402
    ConversationExample,
    DatasetBuilder,
    DatasetConfig,
    FineTuningPipeline,
    TrainingConfig,
)

# a few-hundred-KB random-weight Llama: same module names (q_proj/v_proj/gate_proj...) as a real one,
# so the LoRA target list in _apply_lora is exercised rather than skipped by the fallback branch
TINY_LLAMA = "hf-internal-testing/tiny-random-LlamaForCausalLM"


def _training_config(tmp_path: Path) -> TrainingConfig:
    return TrainingConfig(
        output_dir=str(tmp_path / "ckpt"),
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


def _corpus() -> DatasetBuilder:
    builder = DatasetBuilder(DatasetConfig(max_length=32, test_split=0.25))
    for turn in range(4):
        builder.add_conversation(
            ConversationExample(
                messages=[
                    {"role": "user", "content": f"count to {turn}"},
                    {"role": "assistant", "content": f"counting: {turn}"},
                ]
            )
        )
    return builder


def test_tiny_lora_run_trains_saves_and_reloads(tmp_path: Path) -> None:
    pipeline = FineTuningPipeline(_training_config(tmp_path))
    pipeline.load_model()

    assert pipeline.model is not None
    trainable = sum(p.numel() for p in pipeline.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in pipeline.model.parameters())
    assert 0 < trainable < total  # an adapter attached to something, and froze the base

    builder = _corpus()
    split = builder.build_dataset()
    tokenizer = AutoTokenizer.from_pretrained(TINY_LLAMA)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    train_ds = builder.tokenize_dataset(split["train"], tokenizer)

    metrics = pipeline.train(train_ds)
    assert math.isfinite(metrics["train_loss"]), metrics
    assert metrics["global_step"] > 0

    final = tmp_path / "ckpt" / "final"
    assert (final / "adapter_config.json").exists()
    assert not (final / "config.json").exists() or (final / "adapter_model.safetensors").exists()

    pipeline.load_checkpoint(final)
    assert isinstance(pipeline.model, PeftModel)

    encoded = tokenizer("count to", return_tensors="pt")
    with torch.no_grad():
        out = pipeline.model.generate(
            **encoded, max_new_tokens=4, do_sample=False, pad_token_id=tokenizer.pad_token_id
        )
    assert tokenizer.decode(out[0], skip_special_tokens=True).startswith("count to")


def test_evaluate_reports_loss_and_perplexity(tmp_path: Path) -> None:
    pipeline = FineTuningPipeline(_training_config(tmp_path))
    pipeline.load_model()

    builder = _corpus()
    split = builder.build_dataset()
    tokenizer = AutoTokenizer.from_pretrained(TINY_LLAMA)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    eval_ds = builder.tokenize_dataset(split["test"], tokenizer)

    result = pipeline.evaluate(eval_ds)
    assert result.num_samples == len(eval_ds)
    assert math.isfinite(result.loss) and result.loss >= 0
    assert result.perplexity >= 1.0
