from __future__ import annotations

from pathlib import Path

import pytest

from raven.unique.fine_tuning import (
    Checkpoint,
    ConversationExample,
    DatasetBuilder,
    DatasetConfig,
    EvalResult,
    FineTuningPipeline,
    TrainingConfig,
)


class TestDatasetBuilder:
    def setup_method(self) -> None:
        self.builder = DatasetBuilder()

    def test_build_texts_empty(self):
        assert self.builder.build_texts() == []

    def test_add_conversation(self):
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        self.builder.add_conversation(conv)
        texts = self.builder.build_texts()
        assert len(texts) == 1

    def test_format_conversation_chat(self):
        conv = ConversationExample(
            system_prompt="You are helpful.",
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
        )
        formatted = self.builder._format_conversation(conv)
        assert "<|system|>" in formatted
        assert "<|user|>" in formatted
        assert "<|assistant|>" in formatted

    def test_format_conversation_instruct(self):
        config = DatasetConfig(format="instruct")
        builder = DatasetBuilder(config)
        conv = ConversationExample(messages=[{"role": "user", "content": "Hi"}])
        formatted = builder._format_conversation(conv)
        assert "### Instruction:" in formatted
        assert "### Response:" in formatted
        assert "Hi" in formatted

    def test_format_conversation_no_system(self):
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        formatted = self.builder._format_conversation(conv)
        assert "<|system|>" not in formatted
        assert formatted.strip().startswith("<|user|>")

    def test_add_code(self):
        from raven.unique.fine_tuning import CodeExample

        code = CodeExample(code="print('hello')", language="python", description="test")
        self.builder.add_code(code)
        texts = self.builder.build_texts()
        assert len(texts) == 1
        assert "print('hello')" in texts[0]

    def test_build_dataset_raises_without_datasets(self):
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        self.builder.add_conversation(conv)
        with pytest.raises(RuntimeError, match=r"datasets.*required"):
            self.builder.build_dataset()

    def test_stats(self):
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        self.builder.add_conversation(conv)
        stats = self.builder.stats()
        assert stats["conversations"] == 1
        assert stats["code_samples"] == 0

    def test_clear(self):
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        self.builder.add_conversation(conv)
        self.builder.clear()
        assert self.builder.build_texts() == []

    def test_add_from_jsonl_missing_file(self):
        with pytest.raises(FileNotFoundError):
            self.builder.add_from_jsonl("/nonexistent/file.jsonl")


class TestFineTuningPipeline:
    def setup_method(self) -> None:
        self.pipeline = FineTuningPipeline()

    def test_initialization_defaults(self):
        assert self.pipeline.config.num_epochs == 3
        assert self.pipeline.config.batch_size == 4
        assert self.pipeline.config.learning_rate == 2e-4
        assert self.pipeline.config.use_lora is True

    def test_initialization_custom_config(self):
        config = TrainingConfig(num_epochs=5, batch_size=8)
        pipeline = FineTuningPipeline(config)
        assert pipeline.config.num_epochs == 5
        assert pipeline.config.batch_size == 8

    def test_resolve_model_name_default(self):
        name = self.pipeline._resolve_model_name()
        assert "llama" in name.lower() or "meta" in name.lower()

    def test_resolve_model_name_custom(self):
        config = TrainingConfig(model_name_or_path="my-org/my-model")
        pipeline = FineTuningPipeline(config)
        assert pipeline._resolve_model_name() == "my-org/my-model"

    def test_resolve_model_name_unknown(self):
        config = TrainingConfig(model_type="nonexistent")
        pipeline = FineTuningPipeline(config)
        with pytest.raises(ValueError, match="Unknown model type"):
            pipeline._resolve_model_name()

    def test_validate_dependencies_missing(self):
        with pytest.raises(RuntimeError, match="Missing required dependencies"):
            self.pipeline._validate_dependencies()

    def test_load_model_raises_without_deps(self):
        with pytest.raises(RuntimeError, match="Missing required dependencies"):
            self.pipeline.load_model()

    def test_evaluate_raises_without_deps(self):
        with pytest.raises(RuntimeError, match="transformers and torch are required"):
            self.pipeline.evaluate(None)

    def test_train_raises_without_deps(self):
        with pytest.raises(RuntimeError, match="transformers and torch are required"):
            self.pipeline.train(None, eval_dataset=None)

    def test_unload_model(self):
        self.pipeline.unload_model()
        assert self.pipeline._model is None
        assert self.pipeline._tokenizer is None

    def test_save_checkpoint_creates_directory(self, tmp_path: Path):
        cp = self.pipeline.save_checkpoint(
            str(tmp_path / "cp1"), step=100, epoch=2, metrics={"loss": 0.5}
        )
        assert cp.step == 100
        assert cp.epoch == 2
        assert cp.metrics == {"loss": 0.5}
        assert (tmp_path / "cp1").exists()
        assert (tmp_path / "cp1" / "checkpoint_meta.json").exists()

    def test_list_checkpoints(self, tmp_path: Path):
        assert self.pipeline.list_checkpoints() == []
        self.pipeline.save_checkpoint(str(tmp_path / "cp1"), step=1)
        assert len(self.pipeline.list_checkpoints()) == 1

    def test_get_best_checkpoint_none(self):
        assert self.pipeline.get_best_checkpoint() is None

    def test_get_model_info_no_model(self):
        info = self.pipeline.get_model_info()
        assert info["model_type"] == "llama"
        assert info["checkpoints"] == 0
