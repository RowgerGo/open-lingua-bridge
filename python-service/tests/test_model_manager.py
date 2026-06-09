"""Tests for the P4 model manager path validation and error codes."""

from __future__ import annotations

import pytest

from olb.config import ModelPaths, ServiceConfig
from olb.errors import ErrorCode, ModelFileMissing, ServiceError
from olb.providers.asr.faster_whisper_provider import _validate_model_dir
from olb.providers.translate.nllb_provider import _validate_model_dir as _nllb_validate
from olb.providers.vad.silero_vad_provider import SileroVadProvider
from olb.providers.tts.piper_provider import PiperTtsProvider
from olb.runtime.model_manager import ModelManager


def test_faster_whisper_path_validator_rejects_empty(tmp_path) -> None:
    with pytest.raises(ModelFileMissing):
        _validate_model_dir("")


def test_faster_whisper_path_validator_rejects_missing(tmp_path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(ModelFileMissing):
        _validate_model_dir(str(missing))


def test_faster_whisper_path_validator_requires_model_bin(tmp_path) -> None:
    empty_dir = tmp_path / "model"
    empty_dir.mkdir()
    with pytest.raises(ModelFileMissing):
        _validate_model_dir(str(empty_dir))


def test_nllb_validator_requires_config_json(tmp_path) -> None:
    empty_dir = tmp_path / "model"
    empty_dir.mkdir()
    with pytest.raises(ModelFileMissing):
        _nllb_validate(str(empty_dir))


def test_silero_vad_rejects_missing_file(tmp_path) -> None:
    missing = tmp_path / "silero.onnx"
    with pytest.raises(ModelFileMissing):
        SileroVadProvider(model_path=str(missing))


def test_piper_rejects_missing_voice_dir(tmp_path) -> None:
    missing = tmp_path / "voices"
    with pytest.raises(ModelFileMissing):
        PiperTtsProvider(voice_dir=str(missing))


def test_piper_loads_valid_voice_bundle(tmp_path) -> None:
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    onnx = voice_dir / "zh-test.onnx"
    onnx.write_bytes(b"fake-onnx-bytes")
    cfg = voice_dir / "zh-test.onnx.json"
    cfg.write_text('{"sample_rate": 22050, "num_speakers": 1}', encoding="utf-8")
    provider = PiperTtsProvider(voice_dir=str(voice_dir), default_voice="zh-test")
    voices = provider.list_voices()
    assert [v["id"] for v in voices] == ["zh-test"]
    assert voices[0]["language"] == "cmn_Hans"


def test_piper_voice_dir_with_no_voices_returns_empty(tmp_path) -> None:
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    provider = PiperTtsProvider(voice_dir=str(voice_dir))
    assert provider.list_voices() == []


def test_model_manager_mock_mode_uses_mocks(tmp_path) -> None:
    cfg = ServiceConfig(data_dir=tmp_path, model_paths=ModelPaths())
    mm = ModelManager(cfg)
    result = mm.load(providers=["vad", "asr", "translate", "tts"], config={"mode": "mock"})
    assert result["mode"] == "mock"
    assert result["loaded"] == ["vad", "asr", "translate", "tts"]
    assert result["failed"] == []


def test_model_manager_real_mode_with_missing_files_raises(tmp_path) -> None:
    cfg = ServiceConfig(data_dir=tmp_path, model_paths=ModelPaths(asr="", vad="", translate="", tts_voice_dir=""))
    mm = ModelManager(cfg)
    with pytest.raises(ServiceError) as exc:
        mm.load(
            providers=["vad", "asr", "translate", "tts"],
            config={"mode": "real"},
        )
    assert exc.value.code in {ErrorCode.MODEL_FILE_MISSING, ErrorCode.MODEL_LOAD_FAILED}


def test_piper_real_mode_partial_missing_falls_back_for_missing_only(tmp_path) -> None:
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    onnx = voice_dir / "en-test.onnx"
    onnx.write_bytes(b"fake")
    cfg_path = voice_dir / "en-test.onnx.json"
    cfg_path.write_text('{"sample_rate": 22050, "num_speakers": 1}', encoding="utf-8")
    cfg = ServiceConfig(
        data_dir=tmp_path,
        model_paths=ModelPaths(
            asr="",
            vad="",
            translate="",
            tts_voice_dir=str(voice_dir),
        ),
    )
    mm = ModelManager(cfg)
    result = mm.load(
        providers=["vad", "asr", "translate", "tts"],
        config={"mode": "real", "tts": {"voice_path": str(voice_dir)}},
    )
    # TTS provider loaded successfully; the other three fell back to mocks.
    tts_failed = [f for f in result["failed"] if f["name"] == "tts"]
    assert tts_failed == []
    assert len(result["failed"]) == 3
    assert mm.list_voices()[0]["id"] == "en-test"
