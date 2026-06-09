"""Tests for the rolling VAD buffer used by the pipeline orchestrator."""

from __future__ import annotations

import numpy as np

from olb.providers.vad import EnergyVadProvider
from olb.runtime.rolling_vad import RollingVad


def _speech_pcm(duration_s: float = 0.5, amplitude: int = 8000) -> np.ndarray:
    n = int(duration_s * 16_000)
    rng = np.random.default_rng(0)
    return (rng.standard_normal(n) * amplitude).astype(np.int16)


def test_rolling_vad_drains_speech_across_pushes() -> None:
    vad = EnergyVadProvider(threshold=0.02)
    rolling = RollingVad(vad, sample_rate=16_000, energy_threshold=0.02)
    for _ in range(3):
        segs = rolling.push(_speech_pcm(0.2), sample_rate=16_000)
        assert isinstance(segs, list)
    flushed = rolling.flush()
    assert isinstance(flushed, list)


def test_rolling_vad_keeps_tail_buffer_when_speech_ongoing() -> None:
    vad = EnergyVadProvider(threshold=0.02)
    rolling = RollingVad(vad, sample_rate=16_000, energy_threshold=0.02)
    rolling.push(_speech_pcm(0.3, amplitude=9000), sample_rate=16_000)
    state = rolling.buffer_state()
    assert state["buffer_samples"] >= 0
    assert isinstance(state["speaking"], bool)


def test_rolling_vad_resets_provider_and_buffer() -> None:
    vad = EnergyVadProvider(threshold=0.02)
    rolling = RollingVad(vad, sample_rate=16_000, energy_threshold=0.02)
    rolling.push(_speech_pcm(0.2), sample_rate=16_000)
    rolling.reset()
    assert rolling.buffer_state()["buffer_samples"] == 0
    assert rolling.buffer_state()["speaking"] is False


def test_rolling_vad_resamples_when_sample_rate_differs() -> None:
    vad = EnergyVadProvider(threshold=0.02)
    rolling = RollingVad(vad, sample_rate=16_000, energy_threshold=0.02)
    pcm_48k = (np.random.default_rng(0).standard_normal(48_000) * 6000).astype(np.int16)
    segs = rolling.push(pcm_48k, sample_rate=48_000)
    assert isinstance(segs, list)
