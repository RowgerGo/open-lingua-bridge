"""Model manager: lazy loads / unloads provider instances and runs health checks."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..config import ServiceConfig
from ..errors import ErrorCode, ServiceError
from ..providers.asr import FasterWhisperProvider, MockAsrProvider
from ..providers.translate import (
    DictionaryTranslateProvider,
    MockTranslateProvider,
    NllbTranslateProvider,
)
from ..providers.tts import MockTtsProvider, PiperTtsProvider
from ..providers.vad import EnergyVadProvider, SileroVadProvider


@dataclass
class ModelBundle:
    vad: Any
    asr: Any
    translate: Any
    tts: Any
    voices: list[dict] = field(default_factory=list)


class ModelManager:
    """Thread-safe lazy loader for the four providers.

    The MVP supports either the real providers (silero-vad / faster-whisper /
    NLLB / Piper) or the mock providers. The default is ``mock`` so the
    service can boot without heavy model downloads.
    """

    def __init__(self, cfg: ServiceConfig) -> None:
        self._cfg = cfg
        self._lock = threading.RLock()
        self._bundle: ModelBundle | None = None
        self._mode: str = "mock"
        self._config_payload: dict[str, Any] = {}

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def bundle(self) -> ModelBundle:
        with self._lock:
            if self._bundle is None:
                self.load(providers=["vad", "asr", "translate", "tts"], config={"mode": "mock"})
            assert self._bundle is not None
            return self._bundle

    def list_voices(self, language: str | None = None) -> list[dict]:
        return self.bundle.tts.list_voices(language=language)

    def list_models(self) -> dict:
        providers = {"vad": "mock", "asr": "mock", "translate": "mock", "tts": "mock"}
        if self._bundle is not None:
            providers = {
                "vad": type(self._bundle.vad).__name__,
                "asr": type(self._bundle.asr).__name__,
                "translate": type(self._bundle.translate).__name__,
                "tts": type(self._bundle.tts).__name__,
            }
        return {
            "providers": providers,
            "ready": self._bundle is not None,
            "mode": self._mode,
        }

    def load(self, providers: list[str], config: dict[str, Any]) -> dict:
        with self._lock:
            mode = str(config.get("mode", "mock")).lower()
            self._mode = mode
            self._config_payload = config
            try:
                vad_cfg = config.get("vad", {}) or {}
                asr_cfg = config.get("asr", {}) or {}
                mt_cfg = config.get("translate", {}) or {}
                tts_cfg = config.get("tts", {}) or {}

                if mode == "real":
                    vad = SileroVadProvider(sample_rate=int(vad_cfg.get("sample_rate", 16000)))
                    asr = FasterWhisperProvider(
                        model_path=asr_cfg.get("model_path") or self._cfg.model_paths.asr,
                        device=asr_cfg.get("device", "cpu"),
                        compute_type=asr_cfg.get("compute_type", "int8"),
                    )
                    translate = NllbTranslateProvider(
                        model_path=mt_cfg.get("model_path") or self._cfg.model_paths.translate,
                    )
                    tts = PiperTtsProvider(
                        voice_dir=tts_cfg.get("voice_path") or self._cfg.model_paths.tts_voice_dir
                    )
                else:
                    vad = EnergyVadProvider()
                    asr = MockAsrProvider()
                    translate = DictionaryTranslateProvider() or MockTranslateProvider()
                    tts = MockTtsProvider()
            except Exception as exc:  # pragma: no cover - depends on real models
                raise ServiceError(ErrorCode.MODEL_LOAD_FAILED, str(exc)) from exc
            voices = tts.list_voices() if hasattr(tts, "list_voices") else []
            self._bundle = ModelBundle(vad=vad, asr=asr, translate=translate, tts=tts, voices=voices)
            return {
                "loaded": providers,
                "failed": [],
                "mode": self._mode,
                "voices": len(voices),
            }

    def warmup(self, providers: list[str]) -> dict:
        bundle = self.bundle
        for p in providers or ["vad", "asr", "translate", "tts"]:
            if p == "vad":
                bundle.vad.reset()
            elif p == "asr":
                bundle.asr.reset()
            elif p == "translate":
                pass
            elif p == "tts":
                pass
        return {"warmed": providers or ["vad", "asr", "translate", "tts"]}

    def release(self) -> None:
        with self._lock:
            self._bundle = None
