from __future__ import annotations

import pytest

from raven.unique.voice_biometrics import (
    EnrollmentResult,
    SpectralProcessor,
    VerificationResult,
    VoiceBiometrics,
    VoiceEncoder,
    Voiceprint,
    VoiceVerifier,
)


class TestVoiceBiometrics:
    def setup_method(self) -> None:
        self.biometrics = VoiceBiometrics()

    def test_enroll_success(self):
        audio = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        result = self.biometrics.enroll("speaker1", audio)
        assert result.speaker_id == "speaker1"
        assert result.samples_processed == 2
        assert result.success is True
        assert len(result.embedding) == 192

    def test_enroll_empty_samples(self):
        result = self.biometrics.enroll("speaker1", [])
        assert result.success is False
        assert result.error == "No audio samples provided"
        assert result.samples_processed == 0

    def test_enroll_updates_existing(self):
        audio1 = [[0.1, 0.2, 0.3]]
        audio2 = [[0.4, 0.5, 0.6]]
        self.biometrics.enroll("speaker1", audio1)
        self.biometrics.enroll("speaker1", audio2)
        vp = self.biometrics.get_voiceprint("speaker1")
        assert vp is not None
        assert vp.num_samples == 1
        assert vp.speaker_id == "speaker1"

    def test_verify_enrolled_speaker(self):
        audio = [[0.1, 0.2, 0.3]]
        self.biometrics.enroll("speaker1", audio)
        result = self.biometrics.verify("speaker1", [0.1, 0.2, 0.3], anti_spoof=False)
        assert isinstance(result, VerificationResult)
        assert result.speaker_id == "speaker1"

    def test_verify_unknown_speaker(self):
        with pytest.raises(ValueError, match="not enrolled"):
            self.biometrics.verify("unknown", [0.1, 0.2, 0.3])

    def test_get_voiceprint_exists(self):
        audio = [[0.1, 0.2, 0.3]]
        self.biometrics.enroll("speaker1", audio)
        vp = self.biometrics.get_voiceprint("speaker1")
        assert isinstance(vp, Voiceprint)
        assert vp.speaker_id == "speaker1"

    def test_get_voiceprint_nonexistent(self):
        assert self.biometrics.get_voiceprint("nobody") is None

    def test_remove_voiceprint_exists(self):
        audio = [[0.1, 0.2, 0.3]]
        self.biometrics.enroll("speaker1", audio)
        assert self.biometrics.remove_speaker("speaker1") is True
        assert self.biometrics.get_voiceprint("speaker1") is None

    def test_remove_voiceprint_nonexistent(self):
        assert self.biometrics.remove_speaker("nobody") is False

    def test_identify_returns_top_k(self):
        self.biometrics.enroll("alice", [[0.1, 0.2, 0.3]])
        self.biometrics.enroll("bob", [[0.4, 0.5, 0.6]])
        results = self.biometrics.identify([0.1, 0.2, 0.3], top_k=2)
        assert len(results) == 2
        assert all(isinstance(r, VerificationResult) for r in results)

    def test_identify_empty_raises(self):
        with pytest.raises(ValueError, match="No speakers enrolled"):
            self.biometrics.identify([0.1, 0.2, 0.3])

    def test_list_speakers(self):
        self.biometrics.enroll("alice", [[0.1, 0.2, 0.3]])
        self.biometrics.enroll("bob", [[0.4, 0.5, 0.6]])
        speakers = self.biometrics.list_speakers()
        assert len(speakers) == 2
        ids = [s["speaker_id"] for s in speakers]
        assert "alice" in ids
        assert "bob" in ids

    def test_set_threshold(self):
        self.biometrics.set_threshold(0.8)
        assert self.biometrics._verifier.threshold == 0.8

    def test_get_stats(self):
        self.biometrics.enroll("alice", [[0.1, 0.2, 0.3]])
        stats = self.biometrics.get_stats()
        assert stats["enrolled_speakers"] == 1
        assert stats["threshold"] == 0.65


class TestSpectralProcessor:
    def setup_method(self) -> None:
        self.processor = SpectralProcessor()

    def test_extract_spectral_features_without_librosa(self):
        result = self.processor.extract_spectral_features([0.1, 0.2, 0.3])
        assert result == {"error": 1.0}

    def test_detect_spoof_without_librosa(self):
        score = self.processor.detect_spoof([0.1, 0.2, 0.3])
        assert score == 0.0

    def test_extract_mfcc_raises_without_librosa(self):
        with pytest.raises(RuntimeError, match="librosa is required"):
            self.processor.extract_mfcc([0.1, 0.2, 0.3])


class TestVoiceEncoder:
    def setup_method(self) -> None:
        self.encoder = VoiceEncoder()

    def test_fallback_encode_without_numpy(self):
        embedding = self.encoder._fallback_encode([0.1, 0.2, 0.3])
        assert len(embedding) == 192

    def test_fallback_encode_empty(self):
        embedding = self.encoder._fallback_encode([])
        assert len(embedding) == 192

    def test_compute_similarity_cosine(self):
        sim = VoiceEncoder._cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert sim == 1.0

    def test_compute_similarity_orthogonal(self):
        sim = VoiceEncoder._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == 0.0

    def test_compute_similarity_zero_norm(self):
        sim = VoiceEncoder._cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert sim == 0.0


class TestVoiceVerifier:
    def setup_method(self) -> None:
        self.verifier = VoiceVerifier()

    def test_verify_with_default_threshold(self):
        vp = Voiceprint(
            speaker_id="speaker1",
            embedding=[1.0] + [0.0] * 191,
        )
        result = self.verifier.verify([1.0, 0.0, 0.0], vp)
        assert isinstance(result, VerificationResult)
        assert result.speaker_id == "speaker1"
        assert result.threshold == 0.65

    def test_threshold_setter_valid(self):
        self.verifier.threshold = 0.8
        assert self.verifier.threshold == 0.8

    def test_threshold_setter_invalid(self):
        with pytest.raises(ValueError, match="Threshold must be between"):
            self.verifier.threshold = 1.5

    def test_threshold_setter_negative(self):
        with pytest.raises(ValueError, match="Threshold must be between"):
            self.verifier.threshold = -0.1


class TestDataclasses:
    def test_voiceprint_defaults(self):
        vp = Voiceprint(speaker_id="s1", embedding=[1.0, 2.0])
        assert vp.num_samples == 1
        assert vp.created_at == 0.0
        assert vp.metadata == {}

    def test_verification_result_defaults(self):
        result = VerificationResult(
            verified=True, score=0.9, threshold=0.65, speaker_id="s1"
        )
        assert result.latency_ms == 0.0
        assert result.is_spoof is False
        assert result.anti_spoof_score is None

    def test_enrollment_result_defaults(self):
        result = EnrollmentResult(
            speaker_id="s1", samples_processed=2, embedding=[0.1, 0.2]
        )
        assert result.success is True
        assert result.error == ""
