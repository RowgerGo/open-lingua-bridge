"""FastAPI HTTP routes for the Python Model Service.

Only ``GET`` and ``POST`` are exposed. Realtime audio and TTS audio use the
WebSocket endpoint defined in :mod:`olb.app`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..config import ServiceConfig
from ..errors import ErrorCode, ServiceError
from .model_manager import ModelManager
from .session_manager import SessionManager
from ..schemas.protocol import (
    Envelope,
    LanguageChainRequest,
    ModelsLoadRequest,
    ModelsWarmupRequest,
    PrecheckRequest,
    SessionStartRequest,
    SessionStopRequest,
    TestAsrRequest,
    TestTranslateRequest,
    TestTtsRequest,
)


def make_router(cfg: ServiceConfig, mm: ModelManager, sm: SessionManager) -> APIRouter:
    router = APIRouter()

    def require_auth(x_olb_auth_token: str | None = Header(default=None)) -> None:
        if x_olb_auth_token != cfg.auth_token:
            raise HTTPException(status_code=401, detail={"code": ErrorCode.UNAUTHORIZED.value})

    auth = Depends(require_auth)

    @router.get("/health", response_model=None)
    def health(include_models: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"status": "ok", "protocol_version": cfg.protocol_version}
        if include_models:
            data["models"] = mm.list_models()
        return Envelope(data=data).model_dump()

    @router.get("/models", response_model=None)
    def models(provider: str | None = None, include_status: bool = False) -> dict[str, Any]:
        info = mm.list_models()
        if provider:
            info["providers"] = {k: v for k, v in info["providers"].items() if k == provider}
        if not include_status:
            info.pop("mode", None)
        return Envelope(data=info).model_dump()

    @router.get("/voices", response_model=None)
    def voices(language: str | None = None, include_license: bool = False) -> dict[str, Any]:
        items = mm.list_voices(language=language)
        if not include_license:
            for v in items:
                v.pop("license", None)
        return Envelope(data={"voices": items}).model_dump()

    @router.post("/models/load", response_model=None, dependencies=[auth])
    def models_load(body: ModelsLoadRequest) -> dict[str, Any]:
        result = mm.load(providers=body.providers, config=body.config)
        return Envelope(data=result).model_dump()

    @router.post("/models/warmup", response_model=None, dependencies=[auth])
    def models_warmup(body: ModelsWarmupRequest) -> dict[str, Any]:
        return Envelope(data=mm.warmup(providers=body.providers)).model_dump()

    @router.post("/language-chain/check", response_model=None, dependencies=[auth])
    def language_chain(body: LanguageChainRequest) -> dict[str, Any]:
        from ..providers.language import chain_check

        voices = mm.list_voices()
        report = chain_check(body.source_lang, body.target_lang, tts_voices=voices)
        if not report["complete"] and body.require_tts:
            missing = ",".join(report["missing"]) or "tts_voice"
            raise ServiceError(
                ErrorCode.LANGUAGE_CHAIN_INCOMPLETE,
                f"language chain incomplete: missing {missing}",
            )
        return Envelope(data=report).model_dump()

    @router.post("/core/session/precheck", response_model=None, dependencies=[auth])
    def precheck(body: PrecheckRequest) -> dict[str, Any]:
        from ..providers.language import chain_check

        voices = mm.list_voices()
        report = chain_check(body.source_lang, body.target_lang, tts_voices=voices)
        models_loaded = bool(getattr(mm, "_bundle", None) is not None)
        return Envelope(
            data={
                "ready": report["complete"] or not body.require_tts,
                "checks": {
                    "audio_devices": {"ok": True, "details": body.devices},
                    "backend": {"ok": True},
                    "models": {"ok": models_loaded, "providers": mm.list_models()},
                    "language_chain": {
                        "ok": report["complete"],
                        "missing": report["missing"],
                    },
                },
            }
        ).model_dump()

    @router.post("/backend/session/start", response_model=None, dependencies=[auth])
    def session_start(body: SessionStartRequest) -> dict[str, Any]:
        from ..providers.language import chain_check

        chain = chain_check(body.source_lang, body.target_lang, tts_voices=mm.list_voices())
        if not chain["complete"]:
            missing = ",".join(chain["missing"]) or "language_chain"
            raise ServiceError(
                ErrorCode.LANGUAGE_CHAIN_INCOMPLETE,
                f"language chain incomplete: missing {missing}",
            )
        try:
            state = sm.start(
                source_lang=body.source_lang,
                target_lang=body.target_lang,
                direction=body.direction,
                stream_id=body.stream_id,
                session_id=body.session_id,
            )
        except KeyError as exc:
            raise ServiceError(ErrorCode.SESSION_STATE_INVALID, str(exc)) from exc
        return Envelope(
            data={
                "session_id": state.session_id,
                "state": state.state,
                "source_lang": state.source_lang,
                "target_lang": state.target_lang,
                "direction": state.direction,
                "language_chain": chain,
            }
        ).model_dump()

    @router.post("/backend/session/stop", response_model=None, dependencies=[auth])
    def session_stop(body: SessionStopRequest) -> dict[str, Any]:
        try:
            state = sm.stop(body.session_id, flush=body.flush)
        except KeyError as exc:
            raise ServiceError(ErrorCode.SESSION_NOT_FOUND, str(exc)) from exc
        return Envelope(
            data={"session_id": state.session_id, "state": state.state, "flushed": body.flush}
        ).model_dump()

    @router.post("/test/asr", response_model=None, dependencies=[auth])
    def test_asr(body: TestAsrRequest) -> dict[str, Any]:
        import time
        from pathlib import Path

        import numpy as np
        from scipy.io import wavfile

        try:
            rate, data = wavfile.read(str(body.audio_file_path))
        except Exception as exc:
            raise ServiceError(ErrorCode.INVALID_REQUEST, f"cannot read wav: {exc}") from exc
        if data.dtype != np.int16:
            data = (data.astype(np.float32) * 32767.0).astype(np.int16)
        t0 = time.perf_counter()
        result = mm.bundle.asr.feed_segment(data, sample_rate=int(rate), language=body.language)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return Envelope(
            data={
                "text": result.get("text", ""),
                "language": result.get("language", body.language),
                "confidence": result.get("confidence", 0.0),
                "latency_ms": latency_ms,
            }
        ).model_dump()

    @router.post("/test/translate", response_model=None, dependencies=[auth])
    def test_translate(body: TestTranslateRequest) -> dict[str, Any]:
        import time

        t0 = time.perf_counter()
        text = mm.bundle.translate.translate(body.text, body.source_lang, body.target_lang)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return Envelope(data={"translated_text": text, "latency_ms": latency_ms}).model_dump()

    @router.post("/test/tts", response_model=None, dependencies=[auth])
    def test_tts(body: TestTtsRequest) -> dict[str, Any]:
        import numpy as np

        samples, rate, fmt = mm.bundle.tts.synth(body.text, body.voice_id)
        audio_file_path = None
        if body.write_file:
            from scipy.io import wavfile

            out_dir = cfg.data_dir / "tts"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"tts_{int.from_bytes(body.text.encode('utf-8')[:4], 'big') or 1}.wav"
            wavfile.write(str(out_path), int(rate), samples.astype(np.int16))
            audio_file_path = str(out_path.resolve())
        return Envelope(
            data={
                "audio_file_path": audio_file_path,
                "sample_rate": int(rate),
                "channels": 1,
                "sample_format": fmt,
                "duration_ms": int(samples.size / max(rate, 1) * 1000),
            }
        ).model_dump()

    return router
