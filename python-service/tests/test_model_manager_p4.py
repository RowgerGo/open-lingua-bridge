"""Tests for the model manager path validation and provider load semantics."""

from __future__ import annotations

import pytest

from olb.config import ServiceConfig
from olb.errors import ErrorCode, ModelFileMissing, ModelLoadFailed, ServiceError
from olb.runtime.model_manager import ModelManager


def test_model_manager_loads_mock_bundle_by_default() -> None:
    cfg = ServiceConfig.from_env()
    mm = ModelManager(cfg)
    result = mm.load(providers=["vad", "asr", "translate", "tts"], config={"mode": "mock"})
    assert result["mode"] == "mock"
    assert result["loaded"]
    bundle = mm.bundle
    assert bundle.vad is not None
    assert bundle.asr is not None
    assert bundle.translate is not None
    assert bundle.tts is not None


def test_model_manager_real_mode_missing_model_raises() -> None:
    cfg = ServiceConfig.from_env()
    cfg.model_paths.vad = "/no/such/silero.onnx"
    cfg.model_paths.asr = "/no/such/whisper"
    cfg.model_paths.translate = "/no/such/nllb"
    cfg.model_paths.tts_voice_dir = "/no/such/voices"
    mm = ModelManager(cfg)
    with pytest.raises(ServiceError) as exc:
        mm.load(
            providers=["vad", "asr", "translate", "tts"],
            config={"mode": "real"},
        )
    assert exc.value.code in {ErrorCode.MODEL_FILE_MISSING, ErrorCode.MODEL_LOAD_FAILED}


def test_model_manager_raises_when_all_real_providers_have_missing_files() -> None:
    cfg = ServiceConfig.from_env()
    cfg.model_paths.vad = "/no/such/silero.onnx"
    cfg.model_paths.asr = "/no/such/whisper"
    cfg.model_paths.translate = "/no/such/nllb"
    cfg.model_paths.tts_voice_dir = "/no/such/voices"
    mm = ModelManager(cfg)
    with pytest.raises(ServiceError) as exc:
        mm.load(
            providers=["vad", "asr", "translate", "tts"],
            config={"mode": "real"},
        )
    assert exc.value.code in {ErrorCode.MODEL_FILE_MISSING, ErrorCode.MODEL_LOAD_FAILED}


def test_warmup_resets_vad_and_asr() -> None:
    cfg = ServiceConfig.from_env()
    mm = ModelManager(cfg)
    mm.load(providers=["vad", "asr"], config={"mode": "mock"})
    out = mm.warmup(providers=["vad", "asr", "translate", "tts"])
    assert "vad" in out["warmed"]
    assert "asr" in out["warmed"]


def test_model_file_missing_error_maps_to_model_file_missing_code() -> None:
    err = ModelFileMissing("missing")
    assert err.code == ErrorCode.MODEL_FILE_MISSING
    assert "missing" in err.message


def test_model_load_failed_error_maps_to_model_load_failed_code() -> None:
    err = ModelLoadFailed("load failed")
    assert err.code == ErrorCode.MODEL_LOAD_FAILED
