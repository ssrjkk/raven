from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from raven.unique.fine_tuning import (
    Checkpoint,
    DatasetBuilder,
    DatasetConfig,
    FineTuningPipeline,
    TrainingConfig,
    TrainingMonitor,
)


def _patch_wandb():
    """Inject mock wandb into sys.modules and reload the module."""
    mock_wandb = MagicMock()
    mock_run = MagicMock()
    mock_wandb.init.return_value = mock_run
    mock_wandb.Artifact.return_value = MagicMock()
    patcher = patch.dict("sys.modules", {"wandb": mock_wandb})
    patcher.start()
    import raven.unique.fine_tuning as ft
    importlib.reload(ft)
    return mock_wandb, mock_run, patcher


class TestTrainingMonitor:
    def setup_method(self) -> None:
        self.monitor = TrainingMonitor(use_wandb=False)

    def test_init_no_wandb(self):
        monitor = TrainingMonitor(use_wandb=False)
        assert monitor._use_wandb is False
        assert monitor._metrics_log == []

    def test_init_wandb_not_available(self):
        with patch("raven.unique.fine_tuning._WANDB_AVAILABLE", False):
            monitor = TrainingMonitor(use_wandb=True)
            assert monitor._use_wandb is False

    def test_log_metrics_stores_locally(self):
        metrics = {"train/loss": 0.5, "train/learning_rate": 2e-4}
        self.monitor.log_metrics(metrics)
        assert len(self.monitor._metrics_log) == 1
        assert self.monitor._metrics_log[0] == metrics

    def test_log_metrics_multiple_calls(self):
        self.monitor.log_metrics({"loss": 0.5})
        self.monitor.log_metrics({"loss": 0.3})
        self.monitor.log_metrics({"loss": 0.1})
        assert len(self.monitor._metrics_log) == 3

    def test_log_metrics_with_wandb(self):
        mock_wandb, mock_run, patcher = _patch_wandb()
        try:
            import raven.unique.fine_tuning as ft
            monitor = ft.TrainingMonitor(use_wandb=True)
            assert monitor._use_wandb is True
            monitor._run = mock_run
            monitor.log_metrics({"loss": 0.5})
            mock_wandb.log.assert_called_once_with({"loss": 0.5})
        finally:
            patcher.stop()

    def test_log_checkpoint_with_wandb(self, tmp_path: Path):
        mock_wandb, mock_run, patcher = _patch_wandb()
        try:
            import raven.unique.fine_tuning as ft
            monitor = ft.TrainingMonitor(use_wandb=True)
            monitor._run = mock_run
            cp_dir = tmp_path / "cp-100"
            cp_dir.mkdir()
            (cp_dir / "model.safetensors").write_text("dummy")
            checkpoint = Checkpoint(path=cp_dir, step=100, epoch=2, metrics={"loss": 0.5})
            monitor.log_checkpoint(checkpoint)
            mock_wandb.Artifact.assert_called_once_with("checkpoint-100", type="model")
            mock_run.log_artifact.assert_called_once()
        finally:
            patcher.stop()

    def test_finish_no_wandb(self):
        self.monitor.finish()
        assert len(self.monitor._metrics_log) == 0

    def test_finish_with_wandb(self):
        mock_wandb, mock_run, patcher = _patch_wandb()
        try:
            import raven.unique.fine_tuning as ft
            monitor = ft.TrainingMonitor(use_wandb=True)
            monitor._run = mock_run
            monitor.finish()
            mock_wandb.finish.assert_called_once()
        finally:
            patcher.stop()

    def test_finish_clears_run(self):
        with patch("raven.unique.fine_tuning._WANDB_AVAILABLE", False):
            monitor = TrainingMonitor(use_wandb=True)
            monitor.finish()
            assert len(monitor._metrics_log) == 0


class TestFineTuningPipelineWandbIntegration:
    def setup_method(self) -> None:
        self.pipeline = FineTuningPipeline()

    @pytest.mark.asyncio
    async def test_train_with_wandb_no_wandb_fallback(self):
        with patch("raven.unique.fine_tuning._WANDB_AVAILABLE", False), patch.object(
            self.pipeline, "load_model"
        ) as mock_load, patch.object(self.pipeline, "train", return_value={"train_loss": 0.5}):
            _result_model, result_metrics = await self.pipeline.train_with_wandb(
                TrainingConfig(), MagicMock()
            )
            mock_load.assert_called_once()
            assert result_metrics["train_loss"] == 0.5

    @pytest.mark.asyncio
    async def test_train_with_wandb_calls_wandb_init(self):
        mock_wandb = MagicMock()
        mock_run = MagicMock()
        mock_wandb.init.return_value = mock_run
        with patch.dict("sys.modules", {"wandb": mock_wandb}):
            import raven.unique.fine_tuning as ft
            importlib.reload(ft)
            pipeline = ft.FineTuningPipeline()
            with patch.object(pipeline, "load_model"), patch.object(
                pipeline, "train", return_value={"train_loss": 0.3, "global_step": 50}
            ):
                _, metrics = await pipeline.train_with_wandb(TrainingConfig(), MagicMock())
                mock_wandb.init.assert_called_once()
                assert metrics["train_loss"] == 0.3
