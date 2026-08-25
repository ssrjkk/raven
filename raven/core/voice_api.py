from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.unique.voice_biometrics import VoiceBiometrics

_vb: VoiceBiometrics | None = None


def _get_vb() -> VoiceBiometrics:
    global _vb
    if _vb is None:
        _vb = VoiceBiometrics()
    return _vb


class EnrollRequest(BaseModel):
    speaker_id: str
    audio_samples: list[list[float]]
    sample_rate: int = 16000


class VerifyRequest(BaseModel):
    speaker_id: str
    audio: list[float]
    sample_rate: int = 16000
    anti_spoof: bool = True


class IdentifyRequest(BaseModel):
    audio: list[float]
    sample_rate: int = 16000
    top_k: int = 3


class RemoveRequest(BaseModel):
    speaker_id: str


class ContinuousAuthRequest(BaseModel):
    speaker_id: str
    interval_sec: float = 5.0


def create_voice_router() -> APIRouter:
    router = APIRouter(prefix="/api/voice", tags=["voice"])

    @router.post("/enroll")
    def enroll(req: EnrollRequest):
        vb = _get_vb()
        try:
            result = vb.enroll(req.speaker_id, req.audio_samples, req.sample_rate)
            if not result.success:
                raise HTTPException(400, result.error)
            return {
                "speaker_id": result.speaker_id,
                "samples_processed": result.samples_processed,
                "success": True,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Voice enroll error: {}", e)
            raise internal_error(e) from e

    @router.post("/verify")
    def verify(req: VerifyRequest):
        vb = _get_vb()
        try:
            result = vb.verify(req.speaker_id, req.audio, req.sample_rate, req.anti_spoof)
            return {
                "verified": result.verified,
                "score": result.score,
                "threshold": result.threshold,
                "speaker_id": result.speaker_id,
                "latency_ms": result.latency_ms,
                "anti_spoof_score": result.anti_spoof_score,
                "is_spoof": result.is_spoof,
            }
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:
            logger.error("Voice verify error: {}", e)
            raise internal_error(e) from e

    @router.post("/identify")
    def identify(req: IdentifyRequest):
        vb = _get_vb()
        try:
            results = vb.identify(req.audio, req.sample_rate, req.top_k)
            return {
                "results": [
                    {
                        "speaker_id": r.speaker_id,
                        "score": r.score,
                        "verified": r.verified,
                        "threshold": r.threshold,
                    }
                    for r in results
                ]
            }
        except ValueError:
            return {"results": [], "message": "Invalid voice identification request"}
        except Exception as e:
            logger.error("Voice identify error: {}", e)
            raise HTTPException(500, "Voice identification failed") from e

    @router.get("/speakers")
    def list_speakers():
        vb = _get_vb()
        return {"speakers": vb.list_speakers()}

    @router.post("/remove")
    def remove_speaker(req: RemoveRequest):
        vb = _get_vb()
        if vb.remove_speaker(req.speaker_id):
            return {"success": True, "speaker_id": req.speaker_id}
        raise HTTPException(404, f"Speaker '{req.speaker_id}' not found")

    @router.get("/stats")
    def stats():
        vb = _get_vb()
        return vb.get_stats()

    @router.post("/continuous_start")
    def continuous_start(req: ContinuousAuthRequest):
        vb = _get_vb()
        try:
            vb.start_continuous_auth(req.speaker_id, req.interval_sec)
            return {"success": True, "speaker_id": req.speaker_id, "interval_sec": req.interval_sec}
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:
            logger.error("Voice continuous auth error: {}", e)
            raise internal_error(e) from e

    @router.post("/continuous_stop")
    def continuous_stop(req: RemoveRequest):
        vb = _get_vb()
        vb.stop_continuous_auth(req.speaker_id)
        return {"success": True, "speaker_id": req.speaker_id}

    @router.get("/continuous_status/{speaker_id}")
    def continuous_status(speaker_id: str):
        vb = _get_vb()
        status = vb.get_continuous_auth_status(speaker_id)
        if status is None:
            raise HTTPException(404, f"No continuous auth session for '{speaker_id}'")
        return status

    return router
