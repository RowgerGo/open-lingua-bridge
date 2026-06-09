"""silero-vad provider (lazy import)."""

from __future__ import annotations

import numpy as np

from ..base import VadProvider

try:  # silero-vad is optional; tests use the energy fallback.
    import torch  # type: ignore

    _HAS_TORCH = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_TORCH = False


class SileroVadProvider(VadProvider):
    name = "vad-silero"

    def __init__(self, sample_rate: int = 16000) -> None:
        if not _HAS_TORCH:
            raise RuntimeError("silero-vad requires torch; install with `pip install silero-vad`")
        self._sample_rate = sample_rate
        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
        self._model = model
        self._buffer = np.zeros(0, dtype=np.float32)
        self._reset_state = utils[2]

    def reset(self) -> None:
        self._reset_state()
        self._buffer = np.zeros(0, dtype=np.float32)

    def push_pcm(self, pcm: np.ndarray, sample_rate: int) -> list[dict]:
        if sample_rate != self._sample_rate:
            from scipy.signal import resample_poly

            ratio = self._sample_rate / sample_rate
            pcm = resample_poly(pcm, 1, int(round(1 / ratio)))
        pcm = pcm.astype(np.float32) / 32768.0
        pcm = np.concatenate([self._buffer, pcm])
        chunk = 512 if self._sample_rate == 16000 else 256
        out: list[dict] = []
        i = 0
        while i + chunk <= pcm.size:
            prob = float(self._model(torch.from_numpy(pcm[i : i + chunk]), self._sample_rate).item())
            i += chunk
            if prob > 0.5:
                pass
        self._buffer = pcm[i:]
        return out
