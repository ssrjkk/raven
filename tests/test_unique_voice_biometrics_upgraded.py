from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from raven.unique.voice_biometrics import (
    ContinuousAuthenticator,
    ContinuousAuthSession,
    VoiceBiometrics,
)


class TestContinuousAuthSession:
    def test_session_defaults(self):
        session = ContinuousAuthSession(
            user_id="speaker1",
            start_time=100.0,
            last_verified=100.0,
            failures=0,
            status="active",
            confidence=1.0,
        )
        assert session.user_id == "speaker1"
        assert session.status == "active"
        assert session.failures == 0
        assert session.confidence == 1.0

    def test_session_failed_status(self):
        session = ContinuousAuthSession(
            user_id="speaker1",
            start_time=100.0,
            last_verified=100.0,
            failures=3,
            status="failed",
            confidence=0.3,
        )
        assert session.status == "failed"
        assert session.failures == 3
        assert session.confidence == 0.3


class TestContinuousAuthenticator:
    def setup_method(self) -> None:
        self.biometrics = VoiceBiometrics()
        self.biometrics.enroll("speaker1", [[0.1, 0.2, 0.3]])

    def test_init_accepts_voice_biometrics(self):
        auth = ContinuousAuthenticator(self.biometrics)
        assert auth._vb is self.biometrics
        assert auth._sessions == {}
        assert auth._tasks == {}

    @pytest.mark.asyncio
    async def test_start_returns_session(self):
        auth = ContinuousAuthenticator(self.biometrics)
        session = await auth.start(interval_seconds=0.1)
        assert isinstance(session, ContinuousAuthSession)
        assert session.user_id == "speaker1"
        assert session.status == "active"
        assert session.start_time > 0
        auth.stop()

    @pytest.mark.asyncio
    async def test_start_no_enrolled_speakers_raises(self):
        empty_biometrics = VoiceBiometrics()
        auth = ContinuousAuthenticator(empty_biometrics)
        with pytest.raises(ValueError, match="No enrolled speakers"):
            await auth.start()

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self):
        auth = ContinuousAuthenticator(self.biometrics)
        await auth.start(interval_seconds=1.0)
        assert "speaker1" in auth._tasks
        task = auth._tasks["speaker1"]
        assert not task.done()
        auth.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks_and_sets_stopped(self):
        auth = ContinuousAuthenticator(self.biometrics)
        session = await auth.start(interval_seconds=0.5)
        assert session.status == "active"
        auth.stop()
        assert session.status == "stopped"
        assert len(auth._tasks) == 0

    def test_on_failure_registers_callback(self):
        auth = ContinuousAuthenticator(self.biometrics)
        callback = MagicMock()
        auth.on_failure(callback)
        assert callback in auth._global_callbacks

    def test_on_failure_called_on_verification_fail(self):
        auth = ContinuousAuthenticator(self.biometrics)
        callback = MagicMock()
        auth.on_failure(callback)
        auth.set_audio_buffer("speaker1", [1.0, 1.0, 1.0])
        callback()
        callback.assert_called_once()

    def test_set_audio_buffer_stores_audio(self):
        auth = ContinuousAuthenticator(self.biometrics)
        audio = [0.1, 0.2, 0.3]
        auth.set_audio_buffer("speaker1", audio)
        assert auth._audio_buffers["speaker1"] == audio

    def test_get_session_returns_none_for_unknown(self):
        auth = ContinuousAuthenticator(self.biometrics)
        assert auth.get_session("unknown") is None

    @pytest.mark.asyncio
    async def test_get_session_after_start(self):
        auth = ContinuousAuthenticator(self.biometrics)
        await auth.start(interval_seconds=1.0)
        session = auth.get_session("speaker1")
        assert session is not None
        assert session.status == "active"
        auth.stop()

    @pytest.mark.asyncio
    async def test_get_active_sessions_returns_only_active(self):
        auth = ContinuousAuthenticator(self.biometrics)
        session1 = await auth.start(interval_seconds=1.0)
        assert session1 in auth.get_active_sessions()
        auth.stop()
        assert auth.get_active_sessions() == []
