"""faster-whisper provider (lazy import)."""

from __future__ import annotations

import numpy as np

from ..base import AsrProvider


class FasterWhisperProvider(AsrProvider):
    name = "asr-faster-whisper"

    def __init__(self, model_path: str, device: str = "cpu", compute_type: str = "int8") -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("faster-whisper not installed; `pip install faster-whisper`") from exc
        self._model = WhisperModel(model_path, device=device, compute_type=compute_type)

    def reset(self) -> None:
        return None

    def feed_segment(self, pcm: np.ndarray, sample_rate: int, language: str) -> dict:
        if sample_rate != 16000:
            from scipy.signal import resample_poly

            pcm = resample_poly(pcm, 1, sample_rate // 16000)
        audio = pcm.astype(np.float32) / 32768.0
        segments, info = self._model.transcribe(audio, language=language or None, beam_size=1)
        text = "".join(seg.text for seg in segments).strip()
        return {
            "text": text,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "confidence": 0.9,
            "start_ms": 0,
            "end_ms": int(audio.size / 16),
            "words": [],
            "duration_ms": int(audio.size / 16),
        }
