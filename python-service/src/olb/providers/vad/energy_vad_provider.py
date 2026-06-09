"""Lightweight energy-based VAD used as a portable fallback.

The provider can be swapped for silero-vad via :mod:`olb.providers.vad.silero_vad_provider`.
This fallback guarantees the pipeline runs on any Python install without GPU
or large model downloads, which is required for tests and the mock pipeline.
"""

from __future__ import annotations

import numpy as np

from ..base import VadProvider


class EnergyVadProvider(VadProvider):
    name = "vad-energy"

    def __init__(self, threshold: float = 0.012, frame_ms: int = 30, sample_rate: int = 16000) -> None:
        self._threshold = threshold
        self._frame = max(1, sample_rate * frame_ms // 1000)
        self._sample_rate = sample_rate
        self._buffer = np.zeros(0, dtype=np.int16)
        self._speaking = False
        self._segment: list[np.ndarray] = []
        self._closed: list[dict] = []

    def reset(self) -> None:
        self._buffer = np.zeros(0, dtype=np.int16)
        self._speaking = False
        self._segment = []
        self._closed = []

    def push_pcm(self, pcm: np.ndarray, sample_rate: int) -> list[dict]:
        if pcm.size == 0:
            return []
        if sample_rate != self._sample_rate:
            from scipy.signal import resample_poly

            ratio = self._sample_rate / sample_rate
            pcm = resample_poly(pcm, 1, int(round(1 / ratio))).astype(np.int16)
        if self._buffer.size:
            pcm = np.concatenate([self._buffer, pcm])
        closed_now: list[dict] = []
        i = 0
        while i + self._frame <= pcm.size:
            chunk = pcm[i : i + self._frame]
            i += self._frame
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)) / 32768.0)
            if rms >= self._threshold:
                if not self._speaking:
                    self._speaking = True
                    self._segment = []
                self._segment.append(chunk)
            else:
                if self._speaking:
                    if self._segment:
                        seg = np.concatenate(self._segment)
                        closed_now.append({"samples": seg, "sample_rate": self._sample_rate})
                    self._segment = []
                    self._speaking = False
        self._buffer = pcm[i:]
        self._closed.extend(closed_now)
        return closed_now

    def flush(self) -> list[dict]:
        if self._segment:
            seg = np.concatenate(self._segment)
            self._closed.append({"samples": seg, "sample_rate": self._sample_rate})
            self._segment = []
        self._speaking = False
        closed = self._closed
        self._closed = []
        return closed
