"""Abstract provider interfaces for VAD, ASR, translation, and TTS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Iterable

import numpy as np


class VadProvider(ABC):
    """Detects speech segments from a 16 kHz mono PCM stream."""

    name: str = "vad"

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def push_pcm(self, pcm: np.ndarray, sample_rate: int) -> list[dict]:
        """Return a list of newly closed speech segments."""


class AsrProvider(ABC):
    """Streaming ASR over incremental 16 kHz mono PCM."""

    name: str = "asr"

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def feed_segment(self, pcm: np.ndarray, sample_rate: int, language: str) -> dict:
        """Run ASR on a finalized speech segment and return the final result."""


class TranslateProvider(ABC):
    """Batch translator used after a final ASR result lands."""

    name: str = "translate"

    @abstractmethod
    def translate(self, text: str, source_lang: str, target_lang: str) -> str: ...


class TtsProvider(ABC):
    """Synthesizes PCM/WAV audio for a target text."""

    name: str = "tts"

    @abstractmethod
    def list_voices(self, language: str | None = None) -> list[dict]: ...

    @abstractmethod
    def synth(self, text: str, voice_id: str) -> tuple[np.ndarray, int, str]:
        """Return (samples, sample_rate, sample_format)."""


def to_float32(pcm_int16: Iterable[int]) -> np.ndarray:
    arr = np.fromiter(pcm_int16, dtype=np.int16) if not isinstance(pcm_int16, np.ndarray) else pcm_int16
    if arr.dtype != np.int16:
        return arr.astype(np.float32) / 32768.0
    return arr.astype(np.float32) / 32768.0


def int16_to_bytes(pcm: np.ndarray) -> bytes:
    if pcm.dtype != np.int16:
        pcm = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
    return pcm.tobytes()


def pcm_s16le_mono_16k(pcm: np.ndarray, sample_rate: int, channels: int) -> np.ndarray:
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if pcm.dtype == np.float32 or pcm.dtype == np.float64:
        pcm = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
    if sample_rate != 16000:
        from scipy.signal import resample_poly  # type: ignore

        ratio = 16000 / sample_rate
        pcm = resample_poly(pcm, 1, int(round(1 / ratio)))
    return pcm.astype(np.int16, copy=False)
