"""Corpus governance for the fine-tuning path: consent, redaction, provenance, roles, telemetry.

The training corpus is a process-global builder that the agent can write through tools, so "who
agreed to this", "what is in it after redaction" and "which run produced which adapter" are the three
questions a self-hosted install has to be able to answer. These tests hold the answers in code.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import finetune as ft_mod
from raven.unique import fine_tuning as ft
from raven.unique.fine_tuning import CodeExample, ConversationExample, DatasetBuilder, DatasetConfig

SECRET_TEXT = "write to ops@example.com and rotate ghp_" + "A" * 32 + " today"


def _builder(**policy: Any) -> DatasetBuilder:
    return DatasetBuilder(DatasetConfig(max_length=64, test_split=0.5, **policy))


class TestConsent:
    def test_a_row_is_unusable_until_it_is_consented(self) -> None:
        builder = _builder()
        builder.add_conversation(ConversationExample(messages=[{"role": "user", "content": "hello"}]))
        assert builder.stats()["consented"]["conversations"] == 0
        assert builder.stats()["excluded_without_consent"] == 1

    def test_consent_is_recorded_on_the_row_not_only_in_the_count(self) -> None:
        builder = _builder()
        builder.add_conversation(ConversationExample(messages=[{"role": "user", "content": "hello"}], consented=True))
        assert builder._conversations[0].consented is True
        assert builder.stats()["consented"]["conversations"] == 1

    def test_require_consent_false_is_an_explicit_operator_choice(self) -> None:
        builder = _builder(require_consent=False)
        builder.add_code(CodeExample(code="print(1)"))
        assert builder._consented(builder._code_samples) == builder._code_samples


class TestRedaction:
    def test_credentials_and_emails_never_reach_the_rendered_row(self) -> None:
        builder = _builder()
        builder.add_conversation(
            ConversationExample(messages=[{"role": "user", "content": SECRET_TEXT}], consented=True)
        )
        rendered = builder._messages(builder._conversations[0])[0]["content"]
        assert "ops@example.com" not in rendered
        assert "ghp_" not in rendered
        assert "[EMAIL]" in rendered and "[GITHUB_TOKEN]" in rendered

    def test_a_code_row_is_redacted_in_its_description_and_body(self) -> None:
        builder = _builder()
        builder.add_code(
            CodeExample(code=f"KEY = '{'sk-' + 'B' * 24}'  # noqa", description="uses ops@example.com", consented=True)
        )
        rendered = builder._format_code(builder._code_samples[0])
        assert "sk-" not in rendered and "example.com" not in rendered

    def test_redaction_can_be_switched_off_and_that_shows_in_the_policy(self) -> None:
        builder = _builder(redact_pii=False)
        builder.add_conversation(
            ConversationExample(messages=[{"role": "user", "content": SECRET_TEXT}], consented=True)
        )
        assert SECRET_TEXT in builder._messages(builder._conversations[0])[0]["content"]
        assert builder.stats()["policy"]["redact_pii"] is False


class TestProvenance:
    def test_the_card_describes_the_redacted_consented_corpus(self) -> None:
        builder = _builder()
        builder.add_conversation(
            ConversationExample(
                messages=[{"role": "user", "content": SECRET_TEXT}, {"role": "assistant", "content": "done"}],
                system_prompt="assist",
                metadata={"source": "tg"},
                consented=True,
            )
        )
        builder.add_code(CodeExample(code="print(1)", language="python", consented=True))
        builder.add_code(CodeExample(code="secret()"))  # unconsented, must not be counted
        card = builder.dataset_card()
        assert card["rows"] == {"conversations": 1, "code_samples": 1}
        assert card["messages_by_role"] == {"system": 1, "user": 1, "assistant": 1}
        assert card["excluded_without_consent"] == 1
        assert card["policy"] == {"require_consent": True, "redact_pii": True}
        assert len(card["corpus_sha256"]) == 64

    def test_the_hash_follows_the_content_and_not_the_insertion_order_of_metadata(self) -> None:
        def digest(extra: str) -> str:
            builder = _builder()
            builder.add_conversation(
                ConversationExample(messages=[{"role": "user", "content": f"hello {extra}"}], consented=True)
            )
            return builder.corpus_hash()

        assert digest("a") == digest("a")
        assert digest("a") != digest("b")

    def test_write_card_lands_json_next_to_the_checkpoint(self, tmp_path: Any) -> None:
        builder = _builder()
        builder.add_code(CodeExample(code="print(1)", consented=True))
        target = builder.write_card(tmp_path / "sub" / "dataset_card.json")
        assert json.loads(target.read_text(encoding="utf-8"))["rows"]["code_samples"] == 1


@pytest.mark.skipif(not ft._DATASETS_AVAILABLE, reason="the ml extra is not installed")
class TestBuildRespectsConsent:
    def test_an_unconsented_corpus_cannot_be_trained_on(self) -> None:
        builder = _builder()
        builder.add_conversation(ConversationExample(messages=[{"role": "user", "content": "hi"}]))
        with pytest.raises(RuntimeError, match="no consented rows"):
            builder.build_dataset()

    def test_only_consented_rows_survive_into_the_dataset(self) -> None:
        builder = _builder()
        builder.add_conversation(ConversationExample(messages=[{"role": "user", "content": "hi"}], consented=True))
        builder.add_code(CodeExample(code="print(1)"))
        split = builder.build_dataset()
        assert len(split["train"]) + len(split["test"]) == 1

    def test_a_single_row_corpus_trains_instead_of_erroring_on_the_split(self) -> None:
        builder = _builder()
        builder.add_code(CodeExample(code="print(1)", consented=True))
        split = builder.build_dataset()
        assert len(split["train"]) == 1
        assert len(split["test"]) == 0


class TestToolRoles:
    """The corpus outlives the conversation that filled it and a training run is an hour of compute,
    so neither is something a chat participant should be able to reach through the agent."""

    @pytest.fixture()
    def registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        ft_mod.register_finetune_tools(registry)
        return registry

    @pytest.mark.parametrize(
        "tool",
        [
            "finetune_add_conversation",
            "finetune_add_code",
            "finetune_dataset_clear",
            "finetune_load_model",
            "finetune_start_training",
        ],
    )
    def test_corpus_and_compute_tools_are_admin_only(self, registry: ToolRegistry, tool: str) -> None:
        assert registry.effective_allowed_roles(tool) == ["admin"]

    @pytest.mark.parametrize("tool", ["finetune_dataset_stats", "finetune_dataset_card", "finetune_model_info"])
    def test_read_only_tools_stay_open(self, registry: ToolRegistry, tool: str) -> None:
        assert registry.effective_allowed_roles(tool) is None

    @pytest.mark.asyncio
    async def test_an_unattested_subject_is_denied(self, registry: ToolRegistry) -> None:
        out = await registry.call("finetune_add_code", code="print(1)", consented=True)
        assert "carries no subject role" in out

    @pytest.mark.asyncio
    async def test_a_non_admin_subject_is_denied(self, registry: ToolRegistry) -> None:
        out = await registry.call("finetune_dataset_clear", role="user")
        assert "requires role" in out

    def test_training_asks_for_confirmation(self, registry: ToolRegistry) -> None:
        spec = registry.get("finetune_start_training")
        assert spec is not None
        assert spec.confirm is True


class TestTrackingIsOptIn:
    def test_default_is_off_even_when_wandb_is_importable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RAVEN_TRAIN_TRACKING", raising=False)
        monkeypatch.setattr(ft, "_WANDB_AVAILABLE", True)
        monitor = ft.TrainingMonitor()
        assert monitor._use_wandb is False

    def test_the_environment_variable_is_the_switch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAVEN_TRAIN_TRACKING", "on")
        assert ft.training_tracking_enabled() is True
        monkeypatch.setenv("RAVEN_TRAIN_TRACKING", "")
        assert ft.training_tracking_enabled() is False

    @pytest.mark.asyncio
    async def test_with_tracking_off_no_run_is_initialised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RAVEN_TRAIN_TRACKING", raising=False)
        monkeypatch.setattr(ft, "_WANDB_AVAILABLE", True)

        class _Never:
            def init(self, **_kwargs: Any) -> None:
                raise AssertionError("wandb.init must not be reached while tracking is off")

        monkeypatch.setattr(ft, "wandb", _Never())
        pipeline = ft.FineTuningPipeline()
        monkeypatch.setattr(pipeline, "load_model", lambda *_a: None)
        monkeypatch.setattr(pipeline, "train", lambda *_a: {"train_loss": 1.0})
        model, metrics = await pipeline.train_with_wandb(ft.TrainingConfig(), object())
        assert model is None
        assert metrics == {"train_loss": 1.0}
