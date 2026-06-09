"""Tests for the VAD energy fallback and the mock ASR/TTS providers."""

from __future__ import annotations

import numpy as np

from olb.providers.asr import MockAsrProvider
from olb.providers.tts import MockTtsProvider
from olb.providers.vad import EnergyVadProvider


def test_energy_vad_detects_speech_and_silence() -> None:
    vad = EnergyVadProvider(threshold=0.02)
    silent = np.zeros(int(0.2 * 16000), dtype=np.int16)
    speech = (np.random.default_rng(0).standard_normal(int(1.0 * 16000)) * 6000).astype(np.int16)
    speech[-16000 // 4 :] = 0
    closed = vad.push_pcm(np.concatenate([silent, speech, silent]), sample_rate=16000)
    closed += vad.flush()
    assert closed, "expected at least one closed segment from synthetic speech"


def test_mock_asr_returns_deterministic_text() -> None:
    pcm = (np.random.default_rng(1).standard_normal(16000) * 8000).astype(np.int16)
    a = MockAsrProvider().feed_segment(pcm, 16000, "eng_Latn")
    b = MockAsrProvider().feed_segment(pcm, 16000, "eng_Latn")
    assert a["text"] == b["text"]


def test_mock_tts_synthesizes_nonzero_audio() -> None:
    pcm, rate, fmt = MockTtsProvider().synth("Hello world", "mock-eng")
    assert pcm.size > 0
    assert rate > 0
    assert fmt == "pcm_s16le"
