"""HTTP tests for model and language-chain failure envelopes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from olb.app import build_app
from olb.config import ServiceConfig


def _client() -> tuple[ServiceConfig, TestClient]:
    cfg = ServiceConfig.from_env()
    return cfg, TestClient(build_app(cfg))


def test_models_load_reports_model_file_missing_for_empty_path() -> None:
    cfg, client = _client()
    response = client.post(
        "/models/load",
        headers={"X-OLB-Auth-Token": cfg.auth_token},
        json={"providers": ["asr"], "config": {"mode": "real", "asr": {"model_path": ""}}},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "MODEL_FILE_MISSING"


def test_models_load_reports_model_load_failed_for_unknown_provider() -> None:
    cfg, client = _client()
    response = client.post(
        "/models/load",
        headers={"X-OLB-Auth-Token": cfg.auth_token},
        json={"providers": ["unknown"], "config": {"mode": "mock"}},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "MODEL_LOAD_FAILED"


def test_language_chain_check_reports_incomplete_for_unknown_languages() -> None:
    cfg, client = _client()
    response = client.post(
        "/language-chain/check",
        headers={"X-OLB-Auth-Token": cfg.auth_token},
        json={"source_lang": "zz_Unknown", "target_lang": "yy_Unknown", "require_tts": True},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "LANGUAGE_CHAIN_INCOMPLETE"
