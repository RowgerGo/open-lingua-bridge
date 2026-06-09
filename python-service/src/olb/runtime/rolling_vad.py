"""VAD rolling buffer used by the pipeline orchestrator.

The buffer accumulates incoming PCM between ``push`` calls and exposes a
``flush`` method to drain remaining audio as a final (possibly short)
segment. The default thresholds match the energy fallback so behaviour is
stable across the silero / energy providers.

This is intentionally provider-agnostic: the underlying
:class:`VadProvider` decides whether ``push_pcm`` returns closed
segments; the rolling buffer keeps an audio tail that the orchestrator
can hand to the ASR on demand.
"""

from __future__ import annotations

import numpy as np

from ..providers.base import VadProvider

MAX_BUFFER_MS = 30_000
ENERGY_THRESHOLD = 0.012
ENERGY_FRAME_MS = 30
SAMPLE_RATE = 16_000


def _energy_rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)) / 32768.0)


class RollingVad:
    """Stateless wrapper that flushes residual audio for an underlying VAD."""

    def __init__(
        self,
        vad: VadProvider,
        *,
        sample_rate: int = SAMPLE_RATE,
        max_buffer_ms: int = MAX_BUFFER_MS,
        energy_threshold: float = ENERGY_THRESHOLD,
        energy_frame_ms: int = ENERGY_FRAME_MS,
    ) -> None:
        self._vad = vad
        self._sample_rate = sample_rate
        self._max_samples = int(sample_rate * max_buffer_ms / 1000)
        self._energy_threshold = energy_threshold
        self._frame = max(1, sample_rate * energy_frame_ms // 1000)
        self._buffer = np.zeros(0, dtype=np.int16)
        self._speaking = False
        self._segment: list[np.ndarray] = []

    @property
    def vad(self) -> VadProvider:
        return self._vad

    def reset(self) -> None:
        self._vad.reset()
        self._buffer = np.zeros(0, dtype=np.int16)
        self._speaking = False
        self._segment = []

    def _slice_by_energy(self, pcm: np.ndarray) -> list[dict]:
        closed: list[dict] = []
        i = 0
        n = pcm.size
        while i + self._frame <= n:
            chunk = pcm[i : i + self._frame]
            i += self._frame
            if _energy_rms(chunk) >= self._energy_threshold:
                if not self._speaking:
                    self._speaking = True
                    self._segment = []
                self._segment.append(chunk)
            else:
                if self._speaking:
                    if self._segment:
                        closed.append(
                            {
                                "samples": np.concatenate(self._segment),
                                "sample_rate": self._sample_rate,
                            }
                        )
                    self._segment = []
                    self._speaking = False
        return closed, pcm[i:]

    def push(self, pcm: np.ndarray, sample_rate: int) -> list[dict]:
        if pcm.size == 0:
            return []
        if sample_rate != self._sample_rate:
            from scipy.signal import resample_poly

            pcm = resample_poly(
                pcm, 1, int(round(sample_rate / self._sample_rate))
            ).astype(np.int16)
        if self._buffer.size:
            pcm = np.concatenate([self._buffer, pcm])
        if pcm.size > self._max_samples:
            pcm = pcm[-self._max_samples :]
        provider_segments = self._vad.push_pcm(pcm, sample_rate=self._sample_rate)
        closed_now, residual = self._slice_by_energy(pcm)
        self._buffer = residual
        return provider_segments + closed_now

    def flush(self) -> list[dict]:
        closed: list[dict] = []
        if self._segment:
            closed.append(
                {
                    "samples": np.concatenate(self._segment),
                    "sample_rate": self._sample_rate,
                }
            )
            self._segment = []
            self._speaking = False
        if self._buffer.size:
            closed.append(
                {"samples": self._buffer, "sample_rate": self._sample_rate}
            )
            self._buffer = np.zeros(0, dtype=np.int16)
        flushed = self._vad.flush() if hasattr(self._vad, "flush") else []
        return closed + flushed

    def buffer_state(self) -> dict[str, int | bool]:
        return {
            "buffer_samples": int(self._buffer.size),
            "speaking": self._speaking,
        }


def build_rolling_vad(vad: VadProvider) -> RollingVad:
    return RollingVad(vad)
