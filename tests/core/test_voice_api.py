from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.voice_api as voice_mod
from raven.core.voice_api import create_voice_router


@pytest.fixture()
def mock_vb() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def client(mock_vb: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(create_voice_router())
    original = voice_mod._vb
    voice_mod._vb = mock_vb
    try:
        yield TestClient(app)
    finally:
        voice_mod._vb = original


def test_enroll_success(client: TestClient, mock_vb: MagicMock) -> None:
    result = MagicMock()
    result.success = True
    result.speaker_id = "spk1"
    result.samples_processed = 3
    mock_vb.enroll.return_value = result

    resp = client.post(
        "/api/voice/enroll",
        json={"speaker_id": "spk1", "audio_samples": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["speaker_id"] == "spk1"


def test_enroll_failure(client: TestClient, mock_vb: MagicMock) -> None:
    result = MagicMock()
    result.success = False
    result.error = "Not enough samples"
    mock_vb.enroll.return_value = result

    resp = client.post(
        "/api/voice/enroll",
        json={"speaker_id": "spk1", "audio_samples": [[0.1]]},
    )
    assert resp.status_code == 400


def test_verify(client: TestClient, mock_vb: MagicMock) -> None:
    result = MagicMock()
    result.verified = True
    result.score = 0.95
    result.threshold = 0.8
    result.speaker_id = "spk1"
    result.latency_ms = 12.5
    result.anti_spoof_score = 0.99
    result.is_spoof = False
    mock_vb.verify.return_value = result

    resp = client.post(
        "/api/voice/verify",
        json={"speaker_id": "spk1", "audio": [0.1, 0.2, 0.3]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["score"] == 0.95


def test_verify_not_found(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.verify.side_effect = ValueError("Speaker not found")
    resp = client.post(
        "/api/voice/verify",
        json={"speaker_id": "unknown", "audio": [0.1]},
    )
    assert resp.status_code == 404


def test_identify(client: TestClient, mock_vb: MagicMock) -> None:
    r = MagicMock()
    r.speaker_id = "spk1"
    r.score = 0.9
    r.verified = True
    r.threshold = 0.8
    mock_vb.identify.return_value = [r]

    resp = client.post(
        "/api/voice/identify",
        json={"audio": [0.1, 0.2], "top_k": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1


def test_identify_invalid(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.identify.side_effect = ValueError("bad input")
    resp = client.post("/api/voice/identify", json={"audio": []})
    assert resp.status_code == 400


def test_list_speakers(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.list_speakers.return_value = ["spk1", "spk2"]
    resp = client.get("/api/voice/speakers")
    assert resp.status_code == 200
    assert resp.json()["speakers"] == ["spk1", "spk2"]


def test_remove_speaker(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.remove_speaker.return_value = True
    resp = client.post("/api/voice/remove", json={"speaker_id": "spk1"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_remove_speaker_not_found(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.remove_speaker.return_value = False
    resp = client.post("/api/voice/remove", json={"speaker_id": "unknown"})
    assert resp.status_code == 404


def test_stats(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.get_stats.return_value = {"speakers": 2, "total_samples": 10}
    resp = client.get("/api/voice/stats")
    assert resp.status_code == 200
    assert resp.json()["speakers"] == 2


def test_continuous_start(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.start_continuous_auth.return_value = None
    resp = client.post("/api/voice/continuous_start", json={"speaker_id": "spk1", "interval_sec": 5.0})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_continuous_start_not_found(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.start_continuous_auth.side_effect = ValueError("not found")
    resp = client.post("/api/voice/continuous_start", json={"speaker_id": "unknown"})
    assert resp.status_code == 404


def test_continuous_stop(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.stop_continuous_auth.return_value = None
    resp = client.post("/api/voice/continuous_stop", json={"speaker_id": "spk1"})
    assert resp.status_code == 200


def test_continuous_status(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.get_continuous_auth_status.return_value = {"active": True, "speaker_id": "spk1"}
    resp = client.get("/api/voice/continuous_status/spk1")
    assert resp.status_code == 200
    assert resp.json()["active"] is True


def test_continuous_status_not_found(client: TestClient, mock_vb: MagicMock) -> None:
    mock_vb.get_continuous_auth_status.return_value = None
    resp = client.get("/api/voice/continuous_status/unknown")
    assert resp.status_code == 404
