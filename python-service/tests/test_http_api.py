"""Tests for the HTTP control surface (using FastAPI TestClient)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from olb.app import build_app
from olb.config import ServiceConfig


@pytest.fixture()
def client() -> TestClient:
    cfg = ServiceConfig.from_env()
    app = build_app(cfg)
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["code"] == "OK"


def test_models_load_and_session_start(client: TestClient) -> None:
    r = client.post(
        "/models/load",
        headers={"X-OLB-Auth-Token": "dev-token"},
        json={"providers": ["vad", "asr", "translate", "tts"], "config": {"mode": "mock"}},
    )
    assert r.status_code == 200, r.text


def test_tts_test_endpoint_does_not_write_by_default(client: TestClient) -> None:
    r = client.post(
        "/test/tts",
        headers={"X-OLB-Auth-Token": "dev-token"},
        json={"text": "hello", "language": "eng_Latn", "voice_id": "mock-eng"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["audio_file_path"] is None
    r = client.post(
        "/backend/session/start",
        headers={"X-OLB-Auth-Token": "dev-token"},
        json={"source_lang": "cmn_Hans", "target_lang": "eng_Latn"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["session_id"]
    r = client.post(
        "/backend/session/stop",
        headers={"X-OLB-Auth-Token": "dev-token"},
        json={"session_id": sid, "flush": True},
    )
    assert r.status_code == 200, r.text
