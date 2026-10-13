from __future__ import annotations

from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import finetune as ft_mod


class _Cfg:
    pass


class _FakePipeline:
    def __init__(self, load_raises: bool = False, train_raises: bool = False, cps: list[Any] | None = None) -> None:
        self.config = _Cfg()
        self._tokenizer = object()
        self._load_raises = load_raises
        self._train_raises = train_raises
        self._cps = cps if cps is not None else []

    def load_model(self) -> None:
        if self._load_raises:
            raise RuntimeError("no torch")

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": "llama-base",
            "model_type": "llama",
            "trainable_params": 1234567,
            "total_params": 7000000000,
            "checkpoints": len(self._cps),
        }

    def train(self, _tok: Any, _ev: Any) -> dict[str, Any]:
        if self._train_raises:
            raise RuntimeError("nan loss")
        return {
            "train_loss": 0.12345,
            "global_step": 100,
            "epoch": 3,
            "eval_loss": 0.2,
            "eval_perplexity": 1.5,
        }

    def list_checkpoints(self) -> list[Any]:
        return self._cps


class _FakeBuilder:
    def __init__(
        self,
        dataset: dict[str, Any] | None = None,
        build_runtime: bool = False,
        build_other: bool = False,
    ) -> None:
        self._conversations: list[Any] = []
        self._code: list[Any] = []
        self._dataset = dataset if dataset is not None else {"train": [1, 2], "test": []}
        self._build_runtime = build_runtime
        self._build_other = build_other

    def stats(self) -> dict[str, Any]:
        return {
            "conversations": len(self._conversations),
            "code_samples": len(self._code),
            "config": {"max_length": 2048, "format": "alpaca"},
        }

    def add_conversation(self, c: Any) -> None:
        self._conversations.append(c)

    def add_code(self, c: Any) -> None:
        self._code.append(c)

    def build_dataset(self) -> dict[str, Any]:
        if self._build_runtime:
            raise RuntimeError("empty dataset")
        if self._build_other:
            raise ValueError("weird")
        return self._dataset

    def tokenize_dataset(self, data: Any, _tok: Any) -> Any:
        return {"encoded": data}


def _patch(monkeypatch: pytest.MonkeyPatch, builder: _FakeBuilder, pipeline: _FakePipeline) -> None:
    monkeypatch.setattr(ft_mod, "_get_builder", lambda: builder)
    monkeypatch.setattr(ft_mod, "_get_pipeline", lambda: pipeline)


class TestGetters:
    def test_get_pipeline_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ft_mod, "_pipeline", None)

        class _P:
            def __init__(self) -> None:
                return None

        monkeypatch.setattr(ft_mod, "FineTuningPipeline", _P)
        p = ft_mod._get_pipeline()
        assert isinstance(p, _P)
        assert ft_mod._get_pipeline() is p

    def test_get_builder_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ft_mod, "_builder", None)

        class _B:
            def __init__(self) -> None:
                return None

        monkeypatch.setattr(ft_mod, "DatasetBuilder", _B)
        b = ft_mod._get_builder()
        assert isinstance(b, _B)
        assert ft_mod._get_builder() is b


class TestDatasetOps:
    def test_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        out = ft_mod.finetune_dataset_stats()
        assert "Conversations: 0" in out
        assert "Max length: 2048" in out
        assert "Format: alpaca" in out

    def test_add_conversation_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _FakeBuilder()
        _patch(monkeypatch, b, _FakePipeline())
        out = ft_mod.finetune_add_conversation("sys", '[{"role":"user","content":"hi"}]')
        assert out == "Conversation added (1 messages). Total: 1"

    def test_add_conversation_empty_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        assert "Conversation added (0 messages)" in ft_mod.finetune_add_conversation("", "")

    def test_add_conversation_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        assert ft_mod.finetune_add_conversation("", "not-json").startswith("[error] Invalid JSON")

    def test_add_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        out = ft_mod.finetune_add_code("print(1)", "python", "demo")
        assert out == "Code sample added (python, 8 chars). Total: 1"


class TestModelOps:
    def test_load_model_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        out = ft_mod.finetune_load_model("llama", use_lora=True, use_qlora=False)
        assert "Model loaded: llama-base" in out
        assert "Trainable params: 1,234,567" in out

    def test_load_model_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline(load_raises=True))
        assert "[error] Failed to load model" in ft_mod.finetune_load_model()

    def test_model_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline())
        out = ft_mod.finetune_model_info()
        assert "Model: llama-base" in out
        assert "Checkpoints: 0" in out


class TestTraining:
    def test_success_with_eval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _FakeBuilder(dataset={"train": [1], "test": [2]})
        _patch(monkeypatch, b, _FakePipeline())
        out = ft_mod.finetune_start_training()
        assert "Training completed:" in out
        assert "Loss: 0.1235" in out
        assert "Eval loss: 0.2" in out

    def test_success_without_eval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        b = _FakeBuilder(dataset={"train": [1], "test": []})
        _patch(monkeypatch, b, _FakePipeline())
        assert "Perplexity: 1.5" in ft_mod.finetune_start_training()

    def test_dataset_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(build_runtime=True), _FakePipeline())
        assert ft_mod.finetune_start_training() == "[error] Dataset error: empty dataset"

    def test_dataset_generic_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(build_other=True), _FakePipeline())
        assert ft_mod.finetune_start_training() == "[error] Build dataset failed: weird"

    def test_train_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline(train_raises=True))
        assert "[error] Training failed" in ft_mod.finetune_start_training()


class TestCheckpoints:
    def test_no_checkpoints(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline(cps=[]))
        assert ft_mod.finetune_list_checkpoints() == "[info] No checkpoints saved."

    def test_with_checkpoints(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        cps = [SimpleNamespace(step=100, epoch=1, path="/cp/1")]
        _patch(monkeypatch, _FakeBuilder(), _FakePipeline(cps=cps))
        out = ft_mod.finetune_list_checkpoints()
        assert "Checkpoints (1):" in out
        assert "step=100, epoch=1, path=/cp/1" in out


class TestRegistration:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        ft_mod.register_finetune_tools(registry)
        for name in (
            "finetune_dataset_stats",
            "finetune_add_conversation",
            "finetune_add_code",
            "finetune_load_model",
            "finetune_start_training",
            "finetune_model_info",
            "finetune_list_checkpoints",
        ):
            assert registry.get(name) is not None
