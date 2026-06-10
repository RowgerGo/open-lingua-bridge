"""Model manager: lazy loads / unloads provider instances and runs health checks."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..config import ServiceConfig
from ..errors import (
    ErrorCode,
    ModelFileMissing,
    ModelLoadFailed,
    ServiceError,
)
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


@dataclass
class ProviderLoadResult:
    instance: Any
    failed: dict[str, str] | None = None


class ModelManager:
    """Thread-safe lazy loader for the four providers.

    The MVP supports either the real providers (silero-vad / faster-whisper /
    NLLB / Piper) or the mock providers. The default is ``mock`` so the
    service can boot without heavy model downloads.

    Real mode performs path validation before constructing the provider: a
    missing or unreadable file raises :class:`ModelFileMissing`, mapped to
    the protocol code ``MODEL_FILE_MISSING``. Construction errors from the
    underlying library are mapped to ``MODEL_LOAD_FAILED``. A single
    provider failing does not abort the others; the result reports each
    loaded / failed provider individually and the manager falls back to the
    mock provider for that role.
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
            requested = providers or ["vad", "asr", "translate", "tts"]
            valid_providers = {"vad", "asr", "translate", "tts"}
            unknown = [provider for provider in requested if provider not in valid_providers]
            if unknown:
                raise ServiceError(ErrorCode.MODEL_LOAD_FAILED, f"unknown provider: {unknown[0]}")
            mode = str(config.get("mode", "mock")).lower()
            self._mode = mode
            self._config_payload = config
            vad_cfg = config.get("vad", {}) or {}
            asr_cfg = config.get("asr", {}) or {}
            mt_cfg = config.get("translate", {}) or {}
            tts_cfg = config.get("tts", {}) or {}

            def configured_path(provider_cfg: dict[str, Any], key: str, default: str) -> str:
                if key in provider_cfg:
                    return str(provider_cfg.get(key) or "")
                return default

            failed: list[dict[str, str]] = []
            loaded: list[str] = []

            if mode == "real":
                vad_res = self._safe_load_real(
                    "vad",
                    lambda: SileroVadProvider(
                        model_path=configured_path(vad_cfg, "model_path", self._cfg.model_paths.vad),
                        sample_rate=int(vad_cfg.get("sample_rate", 16000)),
                    ),
                )
                vad = vad_res.instance if vad_res.failed is None else EnergyVadProvider()
                if vad_res.failed is not None:
                    failed.append({"name": "vad", **vad_res.failed})
                else:
                    loaded.append("vad")

                asr_res = self._safe_load_real(
                    "asr",
                    lambda: FasterWhisperProvider(
                        model_path=configured_path(asr_cfg, "model_path", self._cfg.model_paths.asr),
                        device=asr_cfg.get("device", "cpu"),
                        compute_type=asr_cfg.get("compute_type", "int8"),
                    ),
                )
                asr = asr_res.instance if asr_res.failed is None else MockAsrProvider()
                if asr_res.failed is not None:
                    failed.append({"name": "asr", **asr_res.failed})
                else:
                    loaded.append("asr")

                translate_res = self._safe_load_real(
                    "translate",
                    lambda: NllbTranslateProvider(
                        model_path=configured_path(mt_cfg, "model_path", self._cfg.model_paths.translate),
                    ),
                )
                fallback_translate = DictionaryTranslateProvider() or MockTranslateProvider()
                translate = translate_res.instance if translate_res.failed is None else fallback_translate
                if translate_res.failed is not None:
                    failed.append({"name": "translate", **translate_res.failed})
                else:
                    loaded.append("translate")

                tts_res = self._safe_load_real(
                    "tts",
                    lambda: PiperTtsProvider(
                        voice_dir=configured_path(tts_cfg, "voice_path", self._cfg.model_paths.tts_voice_dir),
                        default_voice=tts_cfg.get("default_voice"),
                    ),
                )
                tts = tts_res.instance if tts_res.failed is None else MockTtsProvider()
                if tts_res.failed is not None:
                    failed.append({"name": "tts", **tts_res.failed})
                else:
                    loaded.append("tts")
            else:
                vad = EnergyVadProvider()
                asr = MockAsrProvider()
                translate = DictionaryTranslateProvider() or MockTranslateProvider()
                tts = MockTtsProvider()
                loaded = list(requested)

            voices = tts.list_voices() if hasattr(tts, "list_voices") else []
            self._bundle = ModelBundle(vad=vad, asr=asr, translate=translate, tts=tts, voices=voices)

            requested_failed = [item for item in failed if item["name"] in requested]
            if mode == "real" and requested and len(requested_failed) == len(requested):
                first = requested_failed[0]
                code = (
                    ErrorCode.MODEL_FILE_MISSING
                    if first.get("reason") == "missing"
                    else ErrorCode.MODEL_LOAD_FAILED
                )
                raise ServiceError(code, first.get("message", code.value))

            return {
                "loaded": loaded,
                "failed": failed,
                "mode": self._mode,
                "voices": len(voices),
            }

    def _safe_load_real(self, name: str, factory: Any) -> ProviderLoadResult:
        try:
            return ProviderLoadResult(instance=factory())
        except ModelFileMissing as exc:
            return ProviderLoadResult(
                instance=None,
                failed={"reason": "missing", "code": ErrorCode.MODEL_FILE_MISSING.value, "message": exc.message},
            )
        except ModelLoadFailed as exc:
            return ProviderLoadResult(
                instance=None,
                failed={"reason": "load", "code": ErrorCode.MODEL_LOAD_FAILED.value, "message": exc.message},
            )
        except ServiceError as exc:
            return ProviderLoadResult(
                instance=None,
                failed={"reason": "load", "code": exc.code.value, "message": exc.message},
            )

    def warmup(self, providers: list[str]) -> dict:
        bundle = self.bundle
        for p in providers or ["vad", "asr", "translate", "tts"]:
            if p == "vad":
                bundle.vad.reset()
            elif p == "asr":
                bundle.asr.reset()
        return {"warmed": providers or ["vad", "asr", "translate", "tts"]}

    def release(self) -> None:
        with self._lock:
            self._bundle = None
