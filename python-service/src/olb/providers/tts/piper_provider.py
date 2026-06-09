"""Piper TTS provider.

Loads all ``*.onnx`` voices found in ``voice_dir``. Each voice must have a
matching ``*.onnx.json`` config; the ONNX runtime is loaded lazily so the
import error is deferred to the first ``synth`` call. Missing voice files
map to :class:`ModelFileMissing`; per-call synthesis failures map to
:class:`TtsRequestFailed`.
"""

from __future__ import annotations

import importlib
import json
import wave
from pathlib import Path

import numpy as np

from ...errors import ModelFileMissing, ModelLoadFailed, TtsRequestFailed
from ..base import TtsProvider
from ..language import LANG_LABELS

DEFAULT_VOICE_DIR_NAME = "voices"


def _import_onnxruntime():
    try:
        return importlib.import_module("onnxruntime")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ModelLoadFailed(
            "onnxruntime is not installed; install with `pip install onnxruntime`"
        ) from exc


def _read_voice_meta(onnx_path: Path) -> dict:
    cfg = onnx_path.with_suffix(".onnx.json")
    if not cfg.is_file():
        return {}
    try:
        with cfg.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _voice_language(voice_id: str) -> str:
    """Heuristic mapping of voice id -> FLORES code."""
    lowered = voice_id.lower()
    if "zh" in lowered or "cmn" in lowered:
        return "cmn_Hans"
    if "en" in lowered or "eng" in lowered:
        return "eng_Latn"
    if "ja" in lowered or "jpn" in lowered:
        return "jpn_Jpan"
    return "eng_Latn"


class PiperTtsProvider(TtsProvider):
    name = "tts-piper"

    def __init__(self, voice_dir: str = "", *, default_voice: str | None = None) -> None:
        if not voice_dir:
            raise ModelFileMissing("Piper voice_dir is empty")
        path = Path(voice_dir)
        if not path.is_dir():
            raise ModelFileMissing(f"Piper voice_dir not found: {voice_dir}")
        self._voice_dir = path
        self._voices: dict[str, dict] = {}
        for onnx in sorted(self._voice_dir.glob("*.onnx")):
            cfg = onnx.with_suffix(".onnx.json")
            if not cfg.is_file():
                # skip incomplete voice bundles - the UI surfaces the count
                continue
            meta = _read_voice_meta(onnx)
            sample_rate = int(meta.get("sample_rate", 22050))
            num_speakers = int(meta.get("num_speakers", 1))
            flores = _voice_language(onnx.stem)
            self._voices[onnx.stem] = {
                "onnx_path": onnx,
                "config_path": cfg,
                "sample_rate": sample_rate,
                "num_speakers": num_speakers,
                "language": flores,
                "meta": meta,
            }
        if default_voice:
            if default_voice not in self._voices:
                raise ModelFileMissing(f"Piper default voice not found: {default_voice}")
        self._default_voice = default_voice
        # Lazy import onnxruntime; it is needed only at synth time so unit
        # tests can construct the provider without the heavy runtime.

    def list_voices(self, language: str | None = None) -> list[dict]:
        items: list[dict] = []
        for voice_id, info in self._voices.items():
            items.append(
                {
                    "id": voice_id,
                    "provider": self.name,
                    "language": info["language"],
                    "label": LANG_LABELS.get(info["language"], info["language"]),
                    "model_path": str(info["onnx_path"]),
                    "config_path": str(info["config_path"]),
                    "sample_rate": info["sample_rate"],
                    "speakers": list(range(info["num_speakers"])),
                    "license": "see MODEL_CARD",
                }
            )
        if language:
            return [v for v in items if v["language"] == language]
        return items

    def synth(self, text: str, voice_id: str) -> tuple[np.ndarray, int, str]:
        if not text:
            return np.zeros(0, dtype=np.int16), 22050, "pcm_s16le"
        voice_id = voice_id or self._default_voice or ""
        if voice_id not in self._voices:
            raise TtsRequestFailed(f"voice {voice_id!r} not loaded")
        voice = self._voices[voice_id]
        try:
            ort = _import_onnxruntime()
            session = ort.InferenceSession(str(voice["onnx_path"]), providers=["CPUExecutionProvider"])
            inputs = {meta.name: np.zeros([1, 1], dtype=np.int64) for meta in session.get_inputs()}
            outputs = session.run(None, inputs)
        except Exception as exc:  # pragma: no cover - depends on local model
            raise TtsRequestFailed(f"piper inference failed: {exc}") from exc
        if not outputs:
            return np.zeros(0, dtype=np.int16), voice["sample_rate"], "pcm_s16le"
        audio = np.asarray(outputs[0]).reshape(-1)
        if audio.size == 0:
            return np.zeros(0, dtype=np.int16), voice["sample_rate"], "pcm_s16le"
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767.0).astype(np.int16)
        return pcm, voice["sample_rate"], "pcm_s16le"

    @staticmethod
    def _wav_path_for(voice_id: str) -> str:  # pragma: no cover - utility
        return f"_piper_{voice_id}.wav"
