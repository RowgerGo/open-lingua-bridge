"""Mock ASR provider used for unit tests and the dev mock pipeline.

It just echoes the audio duration and a deterministic transcript derived from the
PCM energy. Real ``faster-whisper`` integration lives in
:mod:`olb.providers.asr.faster_whisper_provider`.
"""

from __future__ import annotations

import hashlib

import numpy as np

from ..base import AsrProvider


class MockAsrProvider(AsrProvider):
    name = "asr-mock"

    def reset(self) -> None:
        return None

    def feed_segment(self, pcm: np.ndarray, sample_rate: int, language: str) -> dict:
        duration_ms = int(pcm.size / max(sample_rate, 1) * 1000)
        digest = hashlib.sha1(pcm.tobytes()).hexdigest()[:8]
        text = f"[mock:{language} {duration_ms}ms {digest}]"
        return {
            "text": text,
            "language": language,
            "language_probability": 1.0,
            "confidence": 0.99,
            "start_ms": 0,
            "end_ms": duration_ms,
            "words": [],
            "duration_ms": duration_ms,
        }
