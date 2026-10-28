from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from raven.core.llm.chat_render import render_chat, stop_token_ids
from raven.unique import fine_tuning
from raven.unique.fine_tuning import (
    Checkpoint,
    CodeExample,
    ConversationExample,
    DatasetBuilder,
    DatasetConfig,
    EvalResult,
    FineTuningPipeline,
    TrainingConfig,
)

IM_START = "<|" + "im_start" + "|>"
IM_END = "<|" + "im_end" + "|>"


class _ChatTemplateTokenizer:
    """Renders like ChatML and tokenizes like a fast tokenizer: one id per special, one per char."""

    chat_template: str | None = "template"
    pad_token_id = 0

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_chat_template(
        self, messages: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool
    ) -> Any:
        self.calls.append({"tokenize": tokenize, "add_generation_prompt": add_generation_prompt})
        text = "".join(f"{m['role']}\n{m['content']}{IM_END}\n" for m in messages)
        if add_generation_prompt:
            text += f"{IM_START}assistant\n"
        return self([text])["input_ids"][0] if tokenize else text

    def __call__(self, texts: Any, **kwargs: Any) -> dict[str, Any]:
        if isinstance(texts, str):
            texts = [texts]
        self.calls.append(dict(kwargs, _count=len(texts)))
        add_special = kwargs.get("add_special_tokens", True)
        max_length = int(kwargs.get("max_length", 0))
        encoded: list[list[int]] = []
        for text in texts:
            body = [ord(char) for char in text]
            if add_special:
                body = [1, *body, 2]
            if kwargs.get("truncation") and max_length:
                body = body[:max_length]
            if kwargs.get("padding") == "max_length":
                body = [*body, *([self.pad_token_id] * (max_length - len(body)))]
            encoded.append(body)
        return {
            "input_ids": encoded,
            "attention_mask": [[1] * len(row) for row in encoded],
        }


class _NoTemplateTokenizer(_ChatTemplateTokenizer):
    chat_template = None


def _conversation() -> ConversationExample:
    # consented: build_dataset refuses an unconsented corpus, and these tests are about the render
    return ConversationExample(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}],
        consented=True,
    )


def _skip_without_datasets() -> None:
    if not fine_tuning._DATASETS_AVAILABLE:
        pytest.skip("the datasets library is not installed")


class TestDatasetBuilder:
    def setup_method(self) -> None:
        self.builder = DatasetBuilder()

    def test_messages_column_folds_the_system_prompt_in_front(self) -> None:
        messages = self.builder._messages(_conversation())
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]

    def test_messages_without_a_system_prompt_start_at_the_first_turn(self) -> None:
        conv = ConversationExample(messages=[{"role": "user", "content": "hello"}])
        assert [m["role"] for m in self.builder._messages(conv)] == ["user"]

    def test_code_is_rendered_with_its_header(self) -> None:
        code = CodeExample(code="print(1)", language="python", description="demo")
        assert "print(1)" in self.builder._format_code(code)
        assert "python" in self.builder._format_code(code)

    def test_build_dataset_carries_messages_not_rendered_text(self) -> None:
        _skip_without_datasets()
        self.builder.add_conversations([_conversation(), _conversation()])
        row = self.builder.build_dataset()["train"][0]
        assert row["messages"][0]["role"] == "system"
        assert row["text"] == ""

    def test_build_dataset_raises_without_datasets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.builder.add_conversation(_conversation())
        # simulate the missing extra: asserting it by assuming it is absent breaks the suite on
        # every machine that has the ml extra installed
        monkeypatch.setattr(fine_tuning, "_DATASETS_AVAILABLE", False)
        with pytest.raises(RuntimeError, match=r"datasets.*required"):
            self.builder.build_dataset()

    def test_tokenize_renders_through_the_tokenizer_template(self) -> None:
        _skip_without_datasets()
        tokenizer = _ChatTemplateTokenizer()
        builder = DatasetBuilder(DatasetConfig(max_length=64, test_split=0.5))
        builder.add_conversations([_conversation(), _conversation()])
        tokenized = builder.tokenize_dataset(builder.build_dataset()["train"], tokenizer)
        assert any(call.get("tokenize") is False for call in tokenizer.calls)
        assert any(call.get("add_special_tokens") is False for call in tokenizer.calls)
        assert len(tokenized) == 1

    def test_code_samples_are_not_wrapped_in_a_chat_template(self) -> None:
        _skip_without_datasets()
        tokenizer = _ChatTemplateTokenizer()
        builder = DatasetBuilder(DatasetConfig(max_length=64, test_split=0.5))
        builder.add_code_samples([CodeExample(code="x = 1", consented=True), CodeExample(code="y = 2", consented=True)])
        builder.tokenize_dataset(builder.build_dataset()["train"], tokenizer)
        encoded = next(call for call in tokenizer.calls if "_count" in call)
        assert encoded["_count"] == 1
        assert not any("tokenize" in call for call in tokenizer.calls)

    def test_stats(self) -> None:
        self.builder.add_conversation(_conversation())
        stats = self.builder.stats()
        assert stats["conversations"] == 1
        assert stats["code_samples"] == 0
        assert "format" not in stats["config"]

    def test_clear_empties_the_builder(self) -> None:
        self.builder.add_conversation(_conversation())
        self.builder.clear()
        assert self.builder._conversations == []

    def test_add_from_jsonl_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            self.builder.add_from_jsonl("/nonexistent/file.jsonl")


class _StopTokenizer:
    """A base model: one advertised eos, a template terminator that is not it."""

    chat_template = None
    eos_token_id = 151_643

    _VOCAB: ClassVar[dict[str, int]] = {"<|" + "im_end" + "|>": 151_645, "<|" + "endoftext" + "|>": 151_643}

    def convert_tokens_to_ids(self, token: str) -> int | None:
        return self._VOCAB.get(token)

    def convert_ids_to_tokens(self, token_id: int) -> str | None:
        return next((name for name, value in self._VOCAB.items() if value == token_id), None)


class _NoVocabularyTokenizer:
    chat_template = None
    eos_token_id = 7

    def convert_tokens_to_ids(self, token: str) -> None:
        return None

    def convert_ids_to_tokens(self, token_id: int) -> None:
        return None


class _UnkAnsweringTokenizer:
    """A tokenizer with no ChatML markup: it answers the lookup with its unk id instead of failing,
    which is what a Llama tokenizer does — and stopping on unk cuts off an answer the moment the
    model hesitates."""

    chat_template = None
    eos_token_id = 2
    unk_token_id = 0

    _VOCAB: ClassVar[dict[str, int]] = {"<s>": 1, "</s>": 2, "<unk>": 0}

    def convert_tokens_to_ids(self, token: str) -> int:
        return self._VOCAB.get(token, self.unk_token_id)

    def convert_ids_to_tokens(self, token_id: int) -> str:
        return next((name for name, value in self._VOCAB.items() if value == token_id), "<unk>")


class TestChatRender:
    def test_generation_stops_on_the_template_terminator_too(self) -> None:
        assert stop_token_ids(_StopTokenizer()) == [151_643, 151_645]

    def test_unknown_terminators_are_not_invented(self) -> None:
        assert stop_token_ids(_NoVocabularyTokenizer()) == [7]

    def test_an_unk_answer_to_the_terminator_lookup_is_not_a_stop_token(self) -> None:
        assert stop_token_ids(_UnkAnsweringTokenizer()) == [2]

    def test_no_tokenizer_no_stop_list(self) -> None:
        assert stop_token_ids(None) == []

    def test_template_tokenizer_is_asked_for_text_not_ids(self) -> None:
        tokenizer = _ChatTemplateTokenizer()
        out = render_chat([{"role": "user", "content": "hi"}], tokenizer)
        assert out.endswith(f"{IM_START}assistant\n")
        assert tokenizer.calls[0]["tokenize"] is False

    def test_fallback_keeps_roles_when_the_tokenizer_has_no_template(self) -> None:
        out = render_chat([{"role": "user", "content": "hi"}], _NoTemplateTokenizer())
        assert out == "user: hi\nassistant:"

    def test_fallback_without_a_generation_prompt(self) -> None:
        out = render_chat([{"role": "user", "content": "hi"}], None, add_generation_prompt=False)
        assert out == "user: hi\n"

    def test_training_and_serving_render_the_same_bytes(self) -> None:
        """The defect this guards: the trainer used to emit its own markup while the provider used
        the tokenizer template, so an adapter was trained on a format no request ever contained."""
        from raven.core.llm.providers.local import LocalAdapterProvider

        tokenizer = _ChatTemplateTokenizer()
        messages = DatasetBuilder()._messages(_conversation())
        provider = LocalAdapterProvider.__new__(LocalAdapterProvider)
        provider._tokenizer = tokenizer
        assert render_chat(messages, tokenizer) == provider._render(messages)

    def test_serving_tokenizes_the_prompt_the_way_training_did(self) -> None:
        """Rendering the same bytes is not enough: a tokenizer that adds a BOS of its own puts the
        request one token out of distribution from every row the adapter trained on."""
        from types import SimpleNamespace

        from raven.core.llm.providers.local import LocalAdapterProvider

        class _Row(list[Any]):
            def to(self, device: object) -> _Row:
                return self

        class _TensorTokenizer(_ChatTemplateTokenizer):
            def __call__(self, texts: Any, **kwargs: Any) -> dict[str, Any]:
                return {key: _Row(value) for key, value in super().__call__(texts, **kwargs).items()}

        messages = DatasetBuilder()._messages(_conversation())
        trained = _TensorTokenizer()
        text = render_chat(messages, trained)
        training_row = trained([text], add_special_tokens=False, truncation=True)["input_ids"][0]

        provider = LocalAdapterProvider.__new__(LocalAdapterProvider)
        provider._tokenizer = _TensorTokenizer()
        provider._model = SimpleNamespace(device="cpu")
        encoded = provider._encode_sync(messages)

        assert provider._tokenizer.calls[-1]["add_special_tokens"] is False
        assert list(encoded["input_ids"][0]) == list(training_row)
        # and the shape this test exists to forbid: a tokenizer that adds a pair of its own on top of
        # what the template already emitted, which a Llama-style base does unless told otherwise
        with_specials = provider._tokenizer([text], truncation=True)["input_ids"][0]
        assert with_specials[0] == 1 and with_specials[-1] == 2
        assert training_row == with_specials[1:-1]

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

    @staticmethod
    def _without_ml_deps(monkeypatch: pytest.MonkeyPatch) -> None:
        """Pretend the optional ml extra is not installed, on any machine."""
        monkeypatch.setattr(fine_tuning, "_TORCH_AVAILABLE", False)
        monkeypatch.setattr(fine_tuning, "_TRANSFORMERS_AVAILABLE", False)
        monkeypatch.setattr(fine_tuning, "_PEFT_AVAILABLE", False)
        monkeypatch.setattr(fine_tuning, "LoraConfig", None)
        monkeypatch.setattr(fine_tuning, "get_peft_model", None)

    def test_validate_dependencies_missing(self, monkeypatch: pytest.MonkeyPatch):
        self._without_ml_deps(monkeypatch)
        with pytest.raises(RuntimeError, match="Missing required dependencies"):
            self.pipeline._validate_dependencies()

    def test_load_model_raises_without_deps(self, monkeypatch: pytest.MonkeyPatch):
        self._without_ml_deps(monkeypatch)
        with pytest.raises(RuntimeError, match="Missing required dependencies"):
            self.pipeline.load_model()

    def test_evaluate_raises_without_deps(self, monkeypatch: pytest.MonkeyPatch):
        self._without_ml_deps(monkeypatch)
        with pytest.raises(RuntimeError, match="transformers and torch are required"):
            self.pipeline.evaluate(None)

    def test_train_raises_without_deps(self, monkeypatch: pytest.MonkeyPatch):
        self._without_ml_deps(monkeypatch)
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
