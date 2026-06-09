"""Deterministic TTS provider used for unit tests and the mock pipeline."""

from __future__ import annotations

import hashlib

import numpy as np

from ..base import TtsProvider


class MockTtsProvider(TtsProvider):
    name = "tts-mock"

    def list_voices(self, language: str | None = None) -> list[dict]:
        voices = [
            {
                "id": "mock-cmn",
                "provider": "tts-mock",
                "language": "cmn_Hans",
                "model_path": "",
                "config_path": "",
                "sample_rate": 22050,
                "speakers": [0],
                "license": "internal",
            },
            {
                "id": "mock-eng",
                "provider": "tts-mock",
                "language": "eng_Latn",
                "model_path": "",
                "config_path": "",
                "sample_rate": 22050,
                "speakers": [0],
                "license": "internal",
            },
        ]
        if language:
            return [v for v in voices if v["language"] == language]
        return voices

    def synth(self, text: str, voice_id: str) -> tuple[np.ndarray, int, str]:
        if not text:
            return np.zeros(0, dtype=np.int16), 22050, "pcm_s16le"
        duration_ms = max(500, min(5000, len(text) * 60))
        sample_rate = 22050
        total = int(sample_rate * duration_ms / 1000)
        digest = hashlib.sha1(text.encode("utf-8")).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        carrier = np.sin(2 * np.pi * 220.0 * np.arange(total) / sample_rate)
        noise = rng.standard_normal(total) * 0.05
        waveform = (carrier + noise) * 0.3
        pcm = (np.clip(waveform, -1.0, 1.0) * 32767.0).astype(np.int16)
        return pcm, sample_rate, "pcm_s16le"
