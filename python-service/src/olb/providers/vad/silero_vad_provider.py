"""silero-vad provider.

Loads a local silero-vad ONNX model from ``model_path``. The bundle is the
ONNX + (optional) config JSON exported from the silero-vad project. We do not
hit PyTorch Hub or download anything; a missing or unreadable model file
raises :class:`ModelFileMissing` so the manager can map the error to the
``MODEL_FILE_MISSING`` / ``MODEL_LOAD_FAILED`` protocol codes.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import numpy as np

from ...errors import ModelFileMissing, ModelLoadFailed
from ..base import VadProvider

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_FRAME_SAMPLES = 512  # silero-vad v5 16 kHz window.
DEFAULT_THRESHOLD = 0.5


def _import_onnxruntime():
    try:
        return importlib.import_module("onnxruntime")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ModelLoadFailed(
            "onnxruntime is not installed; install with `pip install onnxruntime`"
        ) from exc


class SileroVadProvider(VadProvider):
    name = "vad-silero"

    def __init__(
        self,
        model_path: str = "",
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        if not model_path:
            raise ModelFileMissing("silero-vad model_path is empty")
        path = Path(model_path)
        if not path.is_file():
            raise ModelFileMissing(f"silero-vad model not found: {model_path}")
        ort = _import_onnxruntime()
        try:
            self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        except Exception as exc:  # pragma: no cover - depends on local model file
            raise ModelLoadFailed(f"failed to load silero-vad model: {exc}") from exc
        self._sample_rate = sample_rate
        self._threshold = threshold
        self._buffer = np.zeros(0, dtype=np.float32)
        self._state: np.ndarray | None = None
        # silero v5 ONNX inputs are (chunk, h, c). We allocate state lazily.

    def reset(self) -> None:
        self._buffer = np.zeros(0, dtype=np.float32)
        self._state = None

    def push_pcm(self, pcm: np.ndarray, sample_rate: int) -> list[dict]:
        if pcm.size == 0:
            return []
        if sample_rate != self._sample_rate:
            from scipy.signal import resample_poly

            ratio = self._sample_rate / sample_rate
            pcm = resample_poly(pcm, 1, int(round(1 / ratio))).astype(np.float32)
        else:
            pcm = pcm.astype(np.float32)
        pcm = pcm / 32768.0
        pcm = np.concatenate([self._buffer, pcm])
        chunk = DEFAULT_FRAME_SAMPLES
        out: list[dict] = []
        i = 0
        while i + chunk <= pcm.size:
            window = pcm[i : i + chunk]
            i += chunk
            prob = self._infer(window)
        self._buffer = pcm[i:]
        return out

    def flush(self) -> list[dict]:
        out: list[dict] = []
        if self._buffer.size >= DEFAULT_FRAME_SAMPLES:
            tail = self._buffer.copy()
            self._buffer = np.zeros(0, dtype=np.float32)
            out.append({"samples": tail, "sample_rate": self._sample_rate})
        return out

    def _infer(self, chunk: np.ndarray) -> float:
        if self._state is None:
            self._state = np.zeros((2, 1, 64), dtype=np.float32)
        try:
            outs: list[Any] = self._session.run(None, {"input": chunk.reshape(1, -1), "h": self._state[0], "c": self._state[1]})
        except Exception as exc:  # pragma: no cover - depends on local model
            raise ModelLoadFailed(f"silero-vad inference failed: {exc}") from exc
        if len(outs) >= 3:
            self._state = np.stack([outs[1], outs[2]], axis=0)
        prob = float(outs[0].reshape(-1)[0])
        return prob
