"""faster-whisper ASR provider.

Loads a local CTranslate2 Whisper model from ``model_path``. We never trigger
a download. Missing files map to :class:`ModelFileMissing`; import / load
errors map to :class:`ModelLoadFailed`. The provider exposes a partial
``feed_partial`` method used by the rolling-buffer orchestrator to emit
``asr.partial`` events before the segment is finalised.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np

from ...errors import AsrRequestFailed, ModelFileMissing, ModelLoadFailed
from ..base import AsrProvider
from ..language import whisper_code

DEFAULT_SAMPLE_RATE = 16000


def _import_whisper():
    try:
        return importlib.import_module("faster_whisper")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ModelLoadFailed(
            "faster-whisper not installed; install with `pip install faster-whisper`"
        ) from exc


def _validate_model_dir(model_path: str) -> Path:
    path = Path(model_path)
    if not model_path:
        raise ModelFileMissing("faster-whisper model_path is empty")
    if not path.exists():
        raise ModelFileMissing(f"faster-whisper model not found: {model_path}")
    if path.is_dir():
        marker = path / "model.bin"
        if not marker.is_file():
            raise ModelFileMissing(
                f"faster-whisper model directory missing model.bin: {model_path}"
            )
    return path


class FasterWhisperProvider(AsrProvider):
    name = "asr-faster-whisper"

    def __init__(
        self,
        model_path: str = "",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
    ) -> None:
        path = _validate_model_dir(model_path)
        whisper = _import_whisper()
        try:
            self._model = whisper.WhisperModel(str(path), device=device, compute_type=compute_type)
        except Exception as exc:  # pragma: no cover - depends on local model
            raise ModelLoadFailed(f"failed to load faster-whisper model: {exc}") from exc
        self._beam_size = beam_size

    def reset(self) -> None:
        return None

    def feed_segment(self, pcm: np.ndarray, sample_rate: int, language: str) -> dict:
        return self._transcribe(pcm, sample_rate, language, is_partial=False)

    def feed_partial(self, pcm: np.ndarray, sample_rate: int, language: str) -> dict:
        return self._transcribe(pcm, sample_rate, language, is_partial=True)

    def _transcribe(self, pcm: np.ndarray, sample_rate: int, language: str, *, is_partial: bool) -> dict:
        if sample_rate != DEFAULT_SAMPLE_RATE:
            from scipy.signal import resample_poly

            pcm = resample_poly(pcm, 1, sample_rate // DEFAULT_SAMPLE_RATE)
        audio = pcm.astype(np.float32) / 32768.0
        whisper_lang = whisper_code(language) or None
        try:
            segments, info = self._model.transcribe(
                audio,
                language=whisper_lang,
                beam_size=self._beam_size,
                condition_on_previous_text=False,
            )
            collected: list[str] = []
            for seg in segments:
                collected.append(seg.text)
        except Exception as exc:  # pragma: no cover - depends on local model
            raise AsrRequestFailed(f"faster-whisper transcribe failed: {exc}") from exc
        text = "".join(collected).strip()
        duration_ms = int(pcm.size / max(sample_rate, 1) * 1000)
        return {
            "text": text,
            "language": info.language if whisper_lang is None else whisper_lang,
            "language_probability": float(getattr(info, "language_probability", 0.0)),
            "confidence": 0.9,
            "start_ms": 0,
            "end_ms": duration_ms,
            "words": [],
            "duration_ms": duration_ms,
            "is_partial": is_partial,
        }
