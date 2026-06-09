"""Tests for the centralized FLORES / Whisper / TTS language registry."""

from __future__ import annotations

from olb.providers.language import (
    chain_check,
    resolve,
    supported_flores,
    whisper_code,
)


def test_supported_flores_includes_core_pairs() -> None:
    s = supported_flores()
    assert "cmn_Hans" in s
    assert "eng_Latn" in s


def test_whisper_code_maps_flores_to_whisper_codes() -> None:
    assert whisper_code("cmn_Hans") == "zh"
    assert whisper_code("eng_Latn") == "en"
    assert whisper_code("zz_Zzzx") == ""


def test_resolve_reports_provider_capabilities() -> None:
    r = resolve("cmn_Hans", tts_voices=[{"language": "cmn_Hans"}])
    assert r.supported_by_asr
    assert r.supported_by_translate
    assert r.supported_by_tts
    assert r.is_complete


def test_resolve_flags_missing_tts_voice() -> None:
    r = resolve("cmn_Hans", tts_voices=[{"language": "eng_Latn"}])
    assert r.supported_by_asr
    assert not r.supported_by_tts
    assert not r.is_complete


def test_chain_check_reports_missing_components() -> None:
    report = chain_check(
        "cmn_Hans",
        "eng_Latn",
        tts_voices=[{"language": "eng_Latn"}],
    )
    assert report["complete"] is True
    assert report["missing"] == []
    assert report["source"]["flores"] == "cmn_Hans"
    assert report["source"]["whisper"] == "zh"
    assert report["target"]["flores"] == "eng_Latn"


def test_chain_check_reports_missing_tts() -> None:
    report = chain_check("cmn_Hans", "jpn_Jpan", tts_voices=[])
    assert report["complete"] is False
    assert "tts:jpn_Jpan" in report["missing"]
