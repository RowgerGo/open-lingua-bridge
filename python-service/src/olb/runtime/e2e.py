"""Deterministic E2E audio fixtures for mock realtime testing."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2


def synthetic_pcm_stream(
    *,
    duration_ms: int = 1_000,
    sample_rate: int = SAMPLE_RATE,
    tones_hz: tuple[float, ...] = (440.0, 660.0),
    amplitude: float = 0.35,
) -> bytes:
    """Build a deterministic mono pcm_s16le stream from mock voice tones."""

    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not tones_hz:
        raise ValueError("at least one tone is required")

    sample_count = int(sample_rate * duration_ms / 1_000)
    t = np.arange(sample_count, dtype=np.float64) / float(sample_rate)
    signal = np.zeros(sample_count, dtype=np.float64)
    for index, tone in enumerate(tones_hz):
        phase = index * math.pi / 4.0
        signal += np.sin((2.0 * math.pi * float(tone) * t) + phase)
    signal /= float(len(tones_hz))
    fade_len = min(sample_count // 10, sample_rate // 100)
    if fade_len > 0:
        fade = np.linspace(0.0, 1.0, fade_len, endpoint=True)
        signal[:fade_len] *= fade
        signal[-fade_len:] *= fade[::-1]
    pcm = np.clip(signal * amplitude * np.iinfo(np.int16).max, -32768, 32767).astype("<i2")
    return pcm.tobytes()


def write_synthetic_wav(path: str | Path, *, duration_ms: int = 1_000) -> Path:
    """Write the deterministic PCM stream as a tiny mono WAV fixture."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pcm = synthetic_pcm_stream(duration_ms=duration_ms)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return output
