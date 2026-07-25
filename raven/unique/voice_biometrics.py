from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    np = None  # type: ignore[assignment]

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None

try:
    import librosa

    _LIBROSA_AVAILABLE = True
except ImportError:
    _LIBROSA_AVAILABLE = False
    librosa = None

try:
    import speechbrain as sb

    _SPEECHBRAIN_AVAILABLE = True
except ImportError:
    _SPEECHBRAIN_AVAILABLE = False
    sb = None


DEFAULT_SAMPLE_RATE: int = 16000
DEFAULT_EMBEDDING_DIM: int = 192
DEFAULT_VERIFICATION_THRESHOLD: float = 0.65
DEFAULT_ANTI_SPOOF_THRESHOLD: float = 0.5


@dataclass
class Voiceprint:
    speaker_id: str
    embedding: list[float]
    created_at: float = 0.0
    updated_at: float = 0.0
    num_samples: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    verified: bool
    score: float
    threshold: float
    speaker_id: str
    latency_ms: float = 0.0
    anti_spoof_score: float | None = None
    is_spoof: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrollmentResult:
    speaker_id: str
    samples_processed: int
    embedding: list[float]
    success: bool = True
    error: str = ""


@dataclass
class ContinuousAuthSession:
    user_id: str
    start_time: float
    last_verified: float
    failures: int
    status: str  # "active", "stopped", "failed"
    confidence: float


class SpectralProcessor:
    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate

    def extract_mfcc(self, audio: list[float]) -> list[list[float]]:
        if not _LIBROSA_AVAILABLE:
            raise RuntimeError("librosa is required for MFCC extraction")
        audio_arr = np.array(audio, dtype=np.float32)
        mfcc = librosa.feature.mfcc(y=audio_arr, sr=self._sample_rate, n_mfcc=13)
        return mfcc.T.tolist()  # type: ignore[no-any-return]

    def extract_spectral_features(self, audio: list[float]) -> dict[str, float]:
        if not _LIBROSA_AVAILABLE or not _NUMPY_AVAILABLE:
            return {"error": 1.0}
        audio_arr = np.array(audio, dtype=np.float32)
        spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio_arr, sr=self._sample_rate)))
        spectral_rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=audio_arr, sr=self._sample_rate)))
        spectral_bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=audio_arr, sr=self._sample_rate)))
        zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y=audio_arr)))
        rms = float(np.mean(librosa.feature.rms(y=audio_arr)))
        return {
            "spectral_centroid": round(spectral_centroid, 4),
            "spectral_rolloff": round(spectral_rolloff, 4),
            "spectral_bandwidth": round(spectral_bandwidth, 4),
            "zero_crossing_rate": round(zero_crossing_rate, 4),
            "rms": round(rms, 4),
        }

    def detect_spoof(self, audio: list[float]) -> float:
        if not _LIBROSA_AVAILABLE or not _NUMPY_AVAILABLE:
            return 0.0
        features = self.extract_spectral_features(audio)
        if "error" in features:
            return 0.0
        audio_arr = np.array(audio, dtype=np.float32)
        stft = np.abs(librosa.stft(audio_arr))
        spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=audio_arr)))
        energy_ratio = features.get("rms", 0.0) / (features.get("zero_crossing_rate", 0.001) + 1e-8)
        spoof_score = spectral_flatness * 0.4 + min(energy_ratio / 100.0, 1.0) * 0.3
        consistency = self._check_band_consistency(stft)
        spoof_score += (1.0 - consistency) * 0.3
        return float(min(max(spoof_score, 0.0), 1.0))

    def _check_band_consistency(self, stft: np.ndarray) -> float:
        if stft.size == 0:
            return 1.0
        band_energy = np.sum(stft**2, axis=1)
        if np.sum(band_energy) == 0:
            return 1.0
        band_ratio = band_energy / np.sum(band_energy)
        expected = 1.0 / len(band_ratio)
        divergence = float(np.sum(np.abs(band_ratio - expected)))
        return float(max(0.0, 1.0 - divergence / 2.0))


class VoiceEncoder:
    def __init__(self, model_name: str = "speechbrain/spkrec-ecapa-voxceleb", device: str = "") -> None:
        self._model_name = model_name
        self._device = device or ("cuda" if _TORCH_AVAILABLE and torch.cuda.is_available() else "cpu")
        self._model: Any = None
        self._sample_rate: int = DEFAULT_SAMPLE_RATE

    def _load_model(self) -> None:
        if not _SPEECHBRAIN_AVAILABLE:
            raise RuntimeError("speechbrain is required for voice encoding")
        if self._model is not None:
            return
        logger.info("Loading voice encoder model: {} on {}", self._model_name, self._device)
        self._model = sb.inference.SpeakerRecognition.from_hparams(
            source=self._model_name,
            savedir="pretrained_models/spkrec",
            run_opts={"device": self._device},
        )

    def encode(self, audio: list[float], sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[float]:
        if not _NUMPY_AVAILABLE:
            return self._fallback_encode(audio)
        if _SPEECHBRAIN_AVAILABLE:
            try:
                self._load_model()
                audio_arr = np.array(audio, dtype=np.float32)
                if sample_rate != self._sample_rate and _LIBROSA_AVAILABLE:
                    audio_arr = librosa.resample(audio_arr, orig_sr=sample_rate, target_sr=self._sample_rate)
                embedding = self._model.encode_batch(audio_arr)
                if _TORCH_AVAILABLE and isinstance(embedding, torch.Tensor):
                    return embedding.squeeze().cpu().tolist()  # type: ignore[no-any-return]
                return np.asarray(embedding).squeeze().tolist()  # type: ignore[no-any-return]
            except Exception as exc:
                logger.warning("SpeechBrain encoding failed ({}), using fallback", exc)
        return self._fallback_encode(audio)

    def encode_batch(self, audio_batch: list[list[float]], sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[list[float]]:
        return [self.encode(audio, sample_rate) for audio in audio_batch]

    def _fallback_encode(self, audio: list[float]) -> list[float]:
        if not _NUMPY_AVAILABLE:
            return [0.0] * DEFAULT_EMBEDDING_DIM
        audio_arr = np.array(audio, dtype=np.float32)
        if len(audio_arr) == 0:
            return [0.0] * DEFAULT_EMBEDDING_DIM
        segments = np.array_split(audio_arr, DEFAULT_EMBEDDING_DIM)
        embedding = np.array([np.mean(seg) for seg in segments], dtype=np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.tolist()  # type: ignore[no-any-return]

    def compute_similarity(self, embedding_a: list[float], embedding_b: list[float]) -> float:
        if not _NUMPY_AVAILABLE:
            return self._cosine_similarity(embedding_a, embedding_b)
        a = np.array(embedding_a, dtype=np.float32)
        b = np.array(embedding_b, dtype=np.float32)
        dot = float(np.dot(a, b))
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        if norm == 0:
            return 0.0
        return float(np.clip(dot / norm, -1.0, 1.0))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class VoiceVerifier:
    def __init__(self, threshold: float = DEFAULT_VERIFICATION_THRESHOLD) -> None:
        self._threshold = threshold
        self._encoder = VoiceEncoder()

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        self._threshold = value

    def verify(
        self, audio: list[float], voiceprint: Voiceprint, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> VerificationResult:
        start = time.time()
        embedding = self._encoder.encode(audio, sample_rate)
        score = self._encoder.compute_similarity(embedding, voiceprint.embedding)
        latency_ms = (time.time() - start) * 1000.0
        verified = score >= self._threshold
        return VerificationResult(
            verified=verified,
            score=round(score, 4),
            threshold=self._threshold,
            speaker_id=voiceprint.speaker_id,
            latency_ms=round(latency_ms, 2),
        )

    def verify_with_antispoof(
        self,
        audio: list[float],
        voiceprint: Voiceprint,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        anti_spoof_threshold: float = DEFAULT_ANTI_SPOOF_THRESHOLD,
    ) -> VerificationResult:
        start = time.time()
        embedding = self._encoder.encode(audio, sample_rate)
        score = self._encoder.compute_similarity(embedding, voiceprint.embedding)
        processor = SpectralProcessor(sample_rate)
        anti_spoof_score = processor.detect_spoof(audio)
        is_spoof = anti_spoof_score > anti_spoof_threshold
        latency_ms = (time.time() - start) * 1000.0
        verified = score >= self._threshold and not is_spoof
        return VerificationResult(
            verified=verified,
            score=round(score, 4),
            threshold=self._threshold,
            speaker_id=voiceprint.speaker_id,
            latency_ms=round(latency_ms, 2),
            anti_spoof_score=round(anti_spoof_score, 4),
            is_spoof=is_spoof,
        )


class VoiceBiometrics:
    def __init__(self, threshold: float = DEFAULT_VERIFICATION_THRESHOLD) -> None:
        self._encoder = VoiceEncoder()
        self._verifier = VoiceVerifier(threshold)
        self._voiceprints: dict[str, Voiceprint] = {}
        self._continuous_sessions: dict[str, dict[str, Any]] = {}

    def enroll(
        self, speaker_id: str, audio_samples: list[list[float]], sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> EnrollmentResult:
        if not audio_samples:
            return EnrollmentResult(
                speaker_id=speaker_id,
                samples_processed=0,
                embedding=[],
                success=False,
                error="No audio samples provided",
            )
        embeddings = self._encoder.encode_batch(audio_samples, sample_rate)
        if not _NUMPY_AVAILABLE:
            avg_embedding = self._average_embeddings(embeddings)
        else:
            avg_embedding = np.mean(embeddings, axis=0).tolist()

        norm_val = math.sqrt(sum(x * x for x in avg_embedding))
        if norm_val > 0:
            avg_embedding = [x / norm_val for x in avg_embedding]

        now = time.time()
        if speaker_id in self._voiceprints:
            existing = self._voiceprints[speaker_id]
            existing.embedding = avg_embedding
            existing.num_samples = len(audio_samples)
            existing.updated_at = now
        else:
            self._voiceprints[speaker_id] = Voiceprint(
                speaker_id=speaker_id,
                embedding=avg_embedding,
                created_at=now,
                updated_at=now,
                num_samples=len(audio_samples),
            )
        logger.info("Enrolled speaker '{}' with {} samples", speaker_id, len(audio_samples))
        return EnrollmentResult(
            speaker_id=speaker_id,
            samples_processed=len(audio_samples),
            embedding=avg_embedding,
        )

    def verify(
        self, speaker_id: str, audio: list[float], sample_rate: int = DEFAULT_SAMPLE_RATE, anti_spoof: bool = True
    ) -> VerificationResult:
        voiceprint = self._voiceprints.get(speaker_id)
        if voiceprint is None:
            msg = f"Speaker '{speaker_id}' not enrolled"
            raise ValueError(msg)
        if anti_spoof:
            return self._verifier.verify_with_antispoof(audio, voiceprint, sample_rate)
        return self._verifier.verify(audio, voiceprint, sample_rate)

    def identify(
        self, audio: list[float], sample_rate: int = DEFAULT_SAMPLE_RATE, top_k: int = 3
    ) -> list[VerificationResult]:
        if not self._voiceprints:
            raise ValueError("No speakers enrolled")
        results: list[VerificationResult] = []
        embedding = self._encoder.encode(audio, sample_rate)
        for speaker_id, vp in self._voiceprints.items():
            score = self._encoder.compute_similarity(embedding, vp.embedding)
            results.append(
                VerificationResult(
                    verified=score >= self._verifier.threshold,
                    score=round(score, 4),
                    threshold=self._verifier.threshold,
                    speaker_id=speaker_id,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def remove_speaker(self, speaker_id: str) -> bool:
        if speaker_id in self._voiceprints:
            del self._voiceprints[speaker_id]
            self._continuous_sessions.pop(speaker_id, None)
            logger.info("Removed speaker '{}'", speaker_id)
            return True
        return False

    def get_voiceprint(self, speaker_id: str) -> Voiceprint | None:
        return self._voiceprints.get(speaker_id)

    def list_speakers(self) -> list[dict[str, Any]]:
        return [
            {
                "speaker_id": vp.speaker_id,
                "num_samples": vp.num_samples,
                "created_at": vp.created_at,
                "updated_at": vp.updated_at,
                "metadata": vp.metadata,
            }
            for vp in self._voiceprints.values()
        ]

    def start_continuous_auth(self, speaker_id: str, interval_sec: float = 5.0) -> None:
        if speaker_id not in self._voiceprints:
            msg = f"Speaker '{speaker_id}' not enrolled"
            raise ValueError(msg)
        self._continuous_sessions[speaker_id] = {
            "interval": interval_sec,
            "active": True,
            "last_verified": 0.0,
            "score_history": [],
        }
        logger.info("Started continuous auth for '{}' (interval={}s)", speaker_id, interval_sec)

    def stop_continuous_auth(self, speaker_id: str) -> None:
        session = self._continuous_sessions.get(speaker_id)
        if session:
            session["active"] = False
            logger.info("Stopped continuous auth for '{}'", speaker_id)

    def update_continuous_auth(
        self, speaker_id: str, audio: list[float], sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> VerificationResult | None:
        session = self._continuous_sessions.get(speaker_id)
        if not session or not session["active"]:
            return None
        now = time.time()
        if now - session["last_verified"] < session["interval"]:
            return None
        result = self.verify(speaker_id, audio, sample_rate, anti_spoof=True)
        session["last_verified"] = now
        session["score_history"].append(result.score)
        if len(session["score_history"]) > 100:
            session["score_history"] = session["score_history"][-100:]
        return result

    def get_continuous_auth_status(self, speaker_id: str) -> dict[str, Any] | None:
        return self._continuous_sessions.get(speaker_id)

    def set_threshold(self, threshold: float) -> None:
        self._verifier.threshold = threshold
        logger.info("Verification threshold set to {}", threshold)

    def get_stats(self) -> dict[str, Any]:
        return {
            "enrolled_speakers": len(self._voiceprints),
            "continuous_sessions": len(self._continuous_sessions),
            "threshold": self._verifier.threshold,
            "encoder_model": self._encoder._model_name,
        }

    @staticmethod
    def _average_embeddings(embeddings: list[list[float]]) -> list[float]:
        if not embeddings:
            return []
        dim = len(embeddings[0])
        avg = [0.0] * dim
        for emb in embeddings:
            for i in range(dim):
                avg[i] += emb[i]
        return [x / len(embeddings) for x in avg]


class ContinuousAuthenticator:
    def __init__(self, voice_biometrics: VoiceBiometrics) -> None:
        self._vb = voice_biometrics
        self._sessions: dict[str, ContinuousAuthSession] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._failure_callbacks: dict[str, list[Callable[[], None]]] = defaultdict(list)
        self._global_callbacks: list[Callable[[], None]] = []
        self._audio_buffers: dict[str, list[float]] = {}

    def set_audio_buffer(self, user_id: str, audio: list[float]) -> None:
        self._audio_buffers[user_id] = audio

    async def start(self, interval_seconds: float = 5.0) -> ContinuousAuthSession:
        user_id = None
        enrolled = self._vb._voiceprints
        if enrolled:
            user_id = next(iter(enrolled))
        if not user_id:
            raise ValueError("No enrolled speakers found for continuous authentication")
        session = ContinuousAuthSession(
            user_id=user_id,
            start_time=time.time(),
            last_verified=time.time(),
            failures=0,
            status="active",
            confidence=1.0,
        )
        self._sessions[user_id] = session

        async def _verify_loop() -> None:
            while session.status == "active":
                await asyncio.sleep(interval_seconds)
                audio = self._audio_buffers.get(user_id)
                if audio is None:
                    continue
                try:
                    result = self._vb.verify(user_id, audio, anti_spoof=True)
                    session.last_verified = time.time()
                    if not result.verified:
                        session.failures += 1
                        session.confidence = max(0.0, session.confidence - 0.2)
                        for cb in self._global_callbacks:
                            try:
                                cb()
                            except Exception as exc:
                                logger.debug("Failure callback error: {}", exc)
                        for cb in self._failure_callbacks.get(user_id, []):
                            try:
                                cb()
                            except Exception as exc:
                                logger.debug("User failure callback error: {}", exc)
                        if session.failures >= 3:
                            session.status = "failed"
                            logger.warning("Continuous auth failed for user {}", user_id)
                    else:
                        session.confidence = min(1.0, session.confidence + 0.05)
                except Exception as exc:
                    logger.warning("Continuous auth verification error: {}", exc)

        self._tasks[user_id] = asyncio.create_task(_verify_loop())
        logger.info("Continuous authenticator started for user {} (interval={}s)", user_id, interval_seconds)
        return session

    def stop(self) -> None:
        for uid, session in self._sessions.items():
            session.status = "stopped"
            task = self._tasks.get(uid)
            if task and not task.done():
                task.cancel()
        self._tasks.clear()
        logger.info("Continuous authenticator stopped")

    def on_failure(self, callback: Callable[[], None]) -> None:
        self._global_callbacks.append(callback)

    def get_session(self, user_id: str) -> ContinuousAuthSession | None:
        return self._sessions.get(user_id)

    def get_active_sessions(self) -> list[ContinuousAuthSession]:
        return [s for s in self._sessions.values() if s.status == "active"]
