from __future__ import annotations

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.voice_biometrics import VoiceBiometrics

_vb: VoiceBiometrics | None = None


def _get_vb() -> VoiceBiometrics:
    global _vb
    if _vb is None:
        _vb = VoiceBiometrics()
    return _vb


def voice_enroll(speaker_id: str, audio_samples: list[list[float]], sample_rate: int = 16000) -> str:
    vb = _get_vb()
    try:
        result = vb.enroll(speaker_id, audio_samples, sample_rate)
        if result.success:
            return f"Speaker '{speaker_id}' enrolled with {result.samples_processed} samples."
        return f"[error] Enrollment failed: {result.error}"
    except Exception as e:
        logger.error("Voice enroll failed: {}", e)
        return f"[error] Enrollment failed: {e}"


def voice_verify(speaker_id: str, audio: list[float], sample_rate: int = 16000, anti_spoof: bool = True) -> str:
    vb = _get_vb()
    try:
        result = vb.verify(speaker_id, audio, sample_rate, anti_spoof)
        status = "verified" if result.verified else "rejected"
        parts = [
            f"Speaker '{speaker_id}': {status}",
            f"Similarity score: {result.score:.4f} (threshold: {result.threshold})",
            f"Latency: {result.latency_ms:.1f}ms",
        ]
        if result.anti_spoof_score is not None:
            parts.append(f"Anti-spoof score: {result.anti_spoof_score:.4f}{' (spoof detected)' if result.is_spoof else ''}")
        return "\n".join(parts)
    except ValueError as e:
        return f"[error] {e}"
    except Exception as e:
        logger.error("Voice verify failed: {}", e)
        return f"[error] Verification failed: {e}"


def voice_identify(audio: list[float], sample_rate: int = 16000, top_k: int = 3) -> str:
    vb = _get_vb()
    try:
        results = vb.identify(audio, sample_rate, top_k)
        if not results:
            return "[info] No speakers enrolled."
        lines = [f"Top {len(results)} matches:"]
        for r in results:
            lines.append(f"  - {r.speaker_id}: score={r.score:.4f} {'✓' if r.verified else '✗'}")
        return "\n".join(lines)
    except ValueError as e:
        return f"[info] {e}"
    except Exception as e:
        logger.error("Voice identify failed: {}", e)
        return f"[error] Identification failed: {e}"


def voice_list_speakers() -> str:
    vb = _get_vb()
    import time
    speakers = vb.list_speakers()
    if not speakers:
        return "[info] No speakers enrolled."
    lines = [f"Enrolled speakers ({len(speakers)}):"]
    for s in speakers:
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["created_at"]))
        lines.append(f"  - {s['speaker_id']} ({s['num_samples']} samples, enrolled {created})")
    return "\n".join(lines)


def voice_remove_speaker(speaker_id: str) -> str:
    vb = _get_vb()
    if vb.remove_speaker(speaker_id):
        return f"Speaker '{speaker_id}' removed."
    return f"[error] Speaker '{speaker_id}' not found."


def voice_stats() -> str:
    vb = _get_vb()
    stats = vb.get_stats()
    return (
        f"Voice Biometrics Statistics\n"
        f"- Enrolled speakers: {stats['enrolled_speakers']}\n"
        f"- Continuous sessions: {stats['continuous_sessions']}\n"
        f"- Verification threshold: {stats['threshold']}\n"
        f"- Encoder model: {stats['encoder_model']}"
    )


def voice_continuous_auth(speaker_id: str, interval_sec: float = 5.0) -> str:
    vb = _get_vb()
    try:
        vb.start_continuous_auth(speaker_id, interval_sec)
        return (
            f"Continuous authentication started for '{speaker_id}' "
            f"(interval={interval_sec}s). "
            f"Use update_continuous_auth to verify periodically."
        )
    except ValueError as e:
        return f"[error] {e}"
    except Exception as e:
        logger.error("Voice continuous auth failed: {}", e)
        return f"[error] {e}"


def register_voice_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="voice_enroll",
        description="Enroll a speaker by providing multiple audio samples as lists of floats",
        parameters={
            "speaker_id": {"type": "string", "description": "Unique speaker identifier", "required": True},
            "audio_samples": {"type": "array", "description": "List of audio sample arrays (each array is list of floats)", "required": True},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default 16000)", "required": False},
        },
        handler=voice_enroll,
        category="voice",
        timeout=30,
    ))
    registry.register(ToolSpec(
        name="voice_verify",
        description="Verify a speaker against their enrolled voiceprint",
        parameters={
            "speaker_id": {"type": "string", "description": "Speaker identifier to verify", "required": True},
            "audio": {"type": "array", "description": "Audio sample as list of floats", "required": True},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default 16000)", "required": False},
            "anti_spoof": {"type": "boolean", "description": "Enable anti-spoofing detection (default true)", "required": False},
        },
        handler=voice_verify,
        category="voice",
        timeout=15,
    ))
    registry.register(ToolSpec(
        name="voice_identify",
        description="Identify a speaker among all enrolled speakers",
        parameters={
            "audio": {"type": "array", "description": "Audio sample as list of floats", "required": True},
            "sample_rate": {"type": "integer", "description": "Sample rate in Hz (default 16000)", "required": False},
            "top_k": {"type": "integer", "description": "Number of top matches to return (default 3)", "required": False},
        },
        handler=voice_identify,
        category="voice",
        timeout=15,
    ))
    registry.register(ToolSpec(
        name="voice_list_speakers",
        description="List all enrolled speakers",
        parameters={},
        handler=voice_list_speakers,
        category="voice",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="voice_remove_speaker",
        description="Remove an enrolled speaker",
        parameters={
            "speaker_id": {"type": "string", "description": "Speaker identifier to remove", "required": True},
        },
        handler=voice_remove_speaker,
        category="voice",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="voice_stats",
        description="Get voice biometrics statistics",
        parameters={},
        handler=voice_stats,
        category="voice",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="voice_continuous_auth",
        description="Start continuous authentication for a speaker (periodic verification)",
        parameters={
            "speaker_id": {"type": "string", "description": "Speaker identifier", "required": True},
            "interval_sec": {"type": "number", "description": "Verification interval in seconds (default 5.0)", "required": False},
        },
        handler=voice_continuous_auth,
        category="voice",
        timeout=10,
    ))
