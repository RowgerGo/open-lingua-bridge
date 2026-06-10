"""Tests for deterministic P6 synthetic audio helpers."""

from __future__ import annotations

import hashlib
import wave

from olb.runtime.e2e import SAMPLE_RATE, synthetic_pcm_stream, write_synthetic_wav


def test_synthetic_pcm_stream_is_deterministic() -> None:
    first = synthetic_pcm_stream(duration_ms=250)
    second = synthetic_pcm_stream(duration_ms=250)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == "9254fbfa290a9ee434b4fcec62851d2db004ad628828e1acaa6211acfc78b244"


def test_synthetic_wav_fixture_is_deterministic(tmp_path) -> None:
    path = write_synthetic_wav(tmp_path / "synthetic_tone.wav", duration_ms=250)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "447d7933e71eaa6e62c0dd00e0527354d91b762383209ca2282263af016a61dd"
    with wave.open(str(path), "rb") as wav:
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 4_000
