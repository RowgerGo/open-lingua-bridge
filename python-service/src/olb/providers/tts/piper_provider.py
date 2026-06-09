"""Piper TTS provider (lazy import)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..base import TtsProvider


class PiperTtsProvider(TtsProvider):
    name = "tts-piper"

    def __init__(self, voice_dir: str) -> None:
        try:
            from piper import PiperVoice  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("piper-tts not installed; `pip install piper-tts`") from exc
        self._voice_dir = Path(voice_dir)
        self._voices: dict[str, object] = {}
        for onnx in self._voice_dir.glob("*.onnx"):
            cfg = onnx.with_suffix(".onnx.json")
            self._voices[onnx.stem] = PiperVoice.load(str(onnx), config_path=str(cfg) if cfg.exists() else None)

    def list_voices(self, language: str | None = None) -> list[dict]:
        voices = []
        for voice_id in sorted(self._voices):
            lang = "eng_Latn"
            if voice_id.startswith("cmn") or "zh" in voice_id:
                lang = "cmn_Hans"
            voices.append(
                {
                    "id": voice_id,
                    "provider": "tts-piper",
                    "language": lang,
                    "model_path": str(self._voice_dir / f"{voice_id}.onnx"),
                    "config_path": str(self._voice_dir / f"{voice_id}.onnx.json"),
                    "sample_rate": 22050,
                    "speakers": [0],
                    "license": "see MODEL_CARD",
                }
            )
        if language:
            return [v for v in voices if v["language"] == language]
        return voices

    def synth(self, text: str, voice_id: str) -> tuple[np.ndarray, int, str]:
        if voice_id not in self._voices:
            raise KeyError(f"voice {voice_id!r} not loaded")
        voice = self._voices[voice_id]
        with wave.open(f"_piper_{voice_id}.wav", "wb") as _:
            pass
        from piper import SynthesisConfig  # type: ignore

        config = SynthesisConfig()
        chunks: list[bytes] = []
        for chunk in voice.synthesize(text, config):
            chunks.append(chunk.audio_int16_bytes)
        raw = b"".join(chunks)
        if not raw:
            return np.zeros(0, dtype=np.int16), 22050, "pcm_s16le"
        pcm = np.frombuffer(raw, dtype=np.int16)
        sample_rate = int(getattr(voice.config, "sample_rate", 22050))
        return pcm, sample_rate, "pcm_s16le"
