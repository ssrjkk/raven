from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from raven.tools import voice as vmod
from raven.tools.voice import (
    _get_vb,
    register_voice_tools,
    voice_continuous_auth,
    voice_enroll,
    voice_identify,
    voice_list_speakers,
    voice_remove_speaker,
    voice_stats,
    voice_verify,
)


class _FakeVB:
    def __init__(self) -> None:
        self.enroll_result: Any = None
        self.verify_result: Any = None
        self.identify_result: Any = None
        self.speakers: list[dict[str, Any]] = []
        self.removed = True
        self.stats: dict[str, Any] = {}
        self.raise_exc: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.raise_exc is not None:
            raise self.raise_exc

    def enroll(self, speaker_id: str, samples: list[list[float]], rate: int) -> Any:
        self._maybe_raise()
        return self.enroll_result

    def verify(self, speaker_id: str, audio: list[float], rate: int, anti_spoof: bool) -> Any:
        self._maybe_raise()
        return self.verify_result

    def identify(self, audio: list[float], rate: int, top_k: int) -> Any:
        self._maybe_raise()
        return self.identify_result

    def list_speakers(self) -> list[dict[str, Any]]:
        return self.speakers

    def remove_speaker(self, speaker_id: str) -> bool:
        return self.removed

    def get_stats(self) -> dict[str, Any]:
        return self.stats

    def start_continuous_auth(self, speaker_id: str, interval: float) -> None:
        self._maybe_raise()


@pytest.fixture
def vb(monkeypatch: pytest.MonkeyPatch) -> _FakeVB:
    fake = _FakeVB()
    monkeypatch.setattr(vmod, "_get_vb", lambda: fake)
    return fake


def test_get_vb_is_lazy_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class _Ctor:
        def __init__(self) -> None:
            created.append("built")

    orig = vmod._vb
    monkeypatch.setattr(vmod, "VoiceBiometrics", _Ctor)
    vmod._vb = None
    try:
        first = _get_vb()
        second = _get_vb()
        assert first is second
        assert created == ["built"]
    finally:
        vmod._vb = orig


# ---------------------------------------------------------------------------
# enroll / verify / identify
# ---------------------------------------------------------------------------


def test_enroll_success(vb: _FakeVB) -> None:
    vb.enroll_result = SimpleNamespace(success=True, samples_processed=3, error=None)
    assert voice_enroll("sp", [[0.1, 0.2]], 16000) == "Speaker 'sp' enrolled with 3 samples."


def test_enroll_failure_result(vb: _FakeVB) -> None:
    vb.enroll_result = SimpleNamespace(success=False, samples_processed=0, error="too quiet")
    assert voice_enroll("sp", [[]]) == "[error] Enrollment failed: too quiet"


def test_enroll_exception(vb: _FakeVB) -> None:
    vb.raise_exc = RuntimeError("crash")
    assert voice_enroll("sp", [[0.1]]) == "[error] Enrollment failed: crash"


def test_verify_with_anti_spoof(vb: _FakeVB) -> None:
    vb.verify_result = SimpleNamespace(
        verified=True,
        score=0.87654,
        threshold=0.75,
        latency_ms=12.34,
        anti_spoof_score=0.12,
        is_spoof=True,
    )
    out = voice_verify("sp", [0.1, 0.2])
    assert "Speaker 'sp': verified" in out
    assert "Similarity score: 0.8765 (threshold: 0.75)" in out
    assert "Latency: 12.3ms" in out
    assert "Anti-spoof score: 0.1200 (spoof detected)" in out


def test_verify_without_anti_spoof(vb: _FakeVB) -> None:
    vb.verify_result = SimpleNamespace(
        verified=False, score=0.4, threshold=0.75, latency_ms=1.0, anti_spoof_score=None, is_spoof=False
    )
    out = voice_verify("sp", [0.1])
    assert "rejected" in out
    assert "Anti-spoof score" not in out


def test_verify_value_error(vb: _FakeVB) -> None:
    vb.raise_exc = ValueError("not enrolled")
    assert voice_verify("sp", [0.1]) == "[error] not enrolled"


def test_verify_exception(vb: _FakeVB) -> None:
    vb.raise_exc = RuntimeError("boom")
    assert voice_verify("sp", [0.1]) == "[error] Verification failed: boom"


def test_identify_results(vb: _FakeVB) -> None:
    vb.identify_result = [
        SimpleNamespace(speaker_id="a", score=0.9, verified=True),
        SimpleNamespace(speaker_id="b", score=0.1, verified=False),
    ]
    out = voice_identify([0.1, 0.2])
    assert out.startswith("Top 2 matches:")
    assert "  - a: score=0.9000 ✓" in out
    assert "  - b: score=0.1000 ✗" in out


def test_identify_empty(vb: _FakeVB) -> None:
    vb.identify_result = []
    assert voice_identify([0.1]) == "[info] No speakers enrolled."


def test_identify_value_error(vb: _FakeVB) -> None:
    vb.raise_exc = ValueError("empty")
    assert voice_identify([0.1]) == "[info] empty"


def test_identify_exception(vb: _FakeVB) -> None:
    vb.raise_exc = RuntimeError("x")
    assert voice_identify([0.1]) == "[error] Identification failed: x"


# ---------------------------------------------------------------------------
# list / remove / stats / continuous
# ---------------------------------------------------------------------------


def test_list_speakers_empty(vb: _FakeVB) -> None:
    vb.speakers = []
    assert voice_list_speakers() == "[info] No speakers enrolled."


def test_list_speakers_formats(vb: _FakeVB) -> None:
    vb.speakers = [{"speaker_id": "sp1", "num_samples": 4, "created_at": 1_700_000_000}]
    out = voice_list_speakers()
    assert "Enrolled speakers (1):" in out
    assert "sp1 (4 samples, enrolled" in out


def test_remove_speaker_found(vb: _FakeVB) -> None:
    vb.removed = True
    assert voice_remove_speaker("sp") == "Speaker 'sp' removed."


def test_remove_speaker_missing(vb: _FakeVB) -> None:
    vb.removed = False
    assert voice_remove_speaker("ghost") == "[error] Speaker 'ghost' not found."


def test_stats(vb: _FakeVB) -> None:
    vb.stats = {
        "enrolled_speakers": 2,
        "continuous_sessions": 1,
        "threshold": 0.75,
        "encoder_model": "ecapa",
    }
    out = voice_stats()
    assert "Enrolled speakers: 2" in out
    assert "Continuous sessions: 1" in out
    assert "Verification threshold: 0.75" in out
    assert "Encoder model: ecapa" in out


def test_continuous_auth_success(vb: _FakeVB) -> None:
    out = voice_continuous_auth("sp", 5.0)
    assert "Continuous authentication started for 'sp'" in out
    assert "interval=5.0s" in out


def test_continuous_auth_value_error(vb: _FakeVB) -> None:
    vb.raise_exc = ValueError("not enrolled")
    assert voice_continuous_auth("sp") == "[error] not enrolled"


def test_continuous_auth_exception(vb: _FakeVB) -> None:
    vb.raise_exc = RuntimeError("x")
    assert voice_continuous_auth("sp") == "[error] x"


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self) -> None:
        self.specs: list[Any] = []

    def register(self, spec: Any) -> None:
        self.specs.append(spec)


def test_register_voice_tools() -> None:
    reg = _FakeRegistry()
    register_voice_tools(reg)  # type: ignore[arg-type]
    names = {s.name for s in reg.specs}
    assert names == {
        "voice_enroll",
        "voice_verify",
        "voice_identify",
        "voice_list_speakers",
        "voice_remove_speaker",
        "voice_stats",
        "voice_continuous_auth",
    }
    assert all(s.category == "voice" for s in reg.specs)
    assert all(callable(s.handler) for s in reg.specs)
