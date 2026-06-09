"""Pipeline orchestrator wires VAD -> ASR -> translate -> TTS together."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import ErrorCode, ServiceError
from ..providers.base import VadProvider
from ..schemas.protocol import BaseMessage, PROTOCOL_VERSION, now_ms
from .metrics import Metrics
from .model_manager import ModelManager
from .rolling_vad import RollingVad, SAMPLE_RATE as ROLLING_SAMPLE_RATE
from .segment_queue import SegmentQueue, SegmentQueueRegistry
from .session_manager import SessionManager

log = logging.getLogger("olb.orchestrator")

EmitFn = Callable[[BaseMessage], Awaitable[None]]


@dataclass
class PipelineConfig:
    source_lang: str
    target_lang: str
    direction: str
    stream_id: str
    sample_rate: int = 16_000
    max_pending: int = 8
    ttl_ms: int = 8_000


class PipelineOrchestrator:
    def __init__(
        self,
        model_manager: ModelManager,
        session_manager: SessionManager,
        metrics: Metrics,
        *,
        queue_registry: SegmentQueueRegistry | None = None,
    ) -> None:
        self._mm = model_manager
        self._sm = session_manager
        self._metrics = metrics
        self._queue_registry = queue_registry or SegmentQueueRegistry()
        self._rolling: dict[str, RollingVad] = {}

    @property
    def metrics(self) -> Metrics:
        return self._metrics

    @property
    def queue_registry(self) -> SegmentQueueRegistry:
        return self._queue_registry

    def _emit(self, emitter: EmitFn | None) -> Callable[[BaseMessage], Awaitable[None]]:
        if emitter is None:
            async def _drop(_msg: BaseMessage) -> None:  # pragma: no cover
                return None
            return _drop
        return emitter

    def _rolling_for(self, session: Any, vad: VadProvider) -> RollingVad:
        sid = session.session_id
        rolling = self._rolling.get(sid)
        if rolling is None:
            rolling = RollingVad(vad)
            self._rolling[sid] = rolling
        return rolling

    def _queue_for(self, session: Any) -> SegmentQueue:
        return self._queue_registry.for_session(session.session_id)

    def evict_expired(self) -> dict[str, list[str]]:
        return self._queue_registry.evict_expired_all()

    def _to_mono_16k_int16(self, pcm: np.ndarray, sample_rate: int, channels: int) -> np.ndarray:
        if pcm.size == 0:
            return pcm.astype(np.int16, copy=False)
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        if pcm.dtype == np.float32 or pcm.dtype == np.float64:
            pcm = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
        elif pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        if sample_rate != ROLLING_SAMPLE_RATE:
            from scipy.signal import resample_poly
            ratio = ROLLING_SAMPLE_RATE / sample_rate
            pcm = resample_poly(pcm, 1, int(round(1 / ratio))).astype(np.int16)
        return pcm

    async def ingest_pcm(
        self,
        session_id: str,
        pcm: np.ndarray,
        sample_rate: int,
        channels: int = 1,
        emitter: EmitFn | None = None,
    ) -> list[str]:
        session = self._sm.get(session_id)
        pcm = self._to_mono_16k_int16(pcm, sample_rate, channels)
        bundle = self._mm.bundle
        rolling = self._rolling_for(session, bundle.vad)
        new_segments = rolling.push(pcm, sample_rate=ROLLING_SAMPLE_RATE)
        flushed = rolling.flush()
        new_segments = list(new_segments) + list(flushed)
        out: list[str] = []
        for seg in new_segments:
            seg_samples = seg.get("samples")
            if seg_samples is None or seg_samples.size == 0:
                continue
            seg_id = await self._run_segment(
                session, np.asarray(seg_samples, dtype=np.int16), ROLLING_SAMPLE_RATE, emitter
            )
            if seg_id is not None:
                out.append(seg_id)
        return out

    async def flush(
        self,
        session_id: str,
        emitter: EmitFn | None = None,
    ) -> list[str]:
        """Drain the rolling buffer for a session and process closed segments."""
        session = self._sm.get(session_id)
        bundle = self._mm.bundle
        rolling = self._rolling_for(session, bundle.vad)
        flushed = rolling.flush()
        out: list[str] = []
        for seg in flushed:
            samples = np.asarray(seg.get("samples", np.zeros(0, dtype=np.int16)), dtype=np.int16)
            if samples.size == 0:
                continue
            seg_id = await self._run_segment(
                session, samples, ROLLING_SAMPLE_RATE, emitter
            )
            if seg_id is not None:
                out.append(seg_id)
        return out

    def stop_session(self, session_id: str) -> None:
        rolling = self._rolling.pop(session_id, None)
        if rolling is not None:
            rolling.reset()
        self._queue_registry.drop_session(session_id)

    async def _run_segment(
        self,
        session: Any,
        pcm: np.ndarray,
        sample_rate: int,
        emitter: EmitFn | None,
    ) -> str | None:
        bundle = self._mm.bundle
        emit = self._emit(emitter)
        queue = self._queue_for(session)
        # Pre-allocate a segment id so we can register the queue slot before
        # the slow path (ASR/MT/TTS) starts; the mark-asr-final lock still
        # uses the same id.
        seg_id = session.next_segment_id()
        accepted, drop_code = queue.enqueue(
            session.session_id, seg_id, samples=int(pcm.size)
        )
        if not accepted:
            await self._emit_dropped(
                emit, session, seg_id, drop_code or "PLAYBACK_QUEUE_OVERLOADED", reason="overloaded"
            )
            return None
        queue.mark_running(seg_id)

        base = {
            "session_id": session.session_id,
            "stream_id": session.stream_id,
            "direction": session.direction,
            "segment_id": seg_id,
            "source_lang": session.source_lang,
            "target_lang": session.target_lang,
            "protocol_version": PROTOCOL_VERSION,
        }

        try:
            partial_text, asr_result, asr_ms = self._run_asr(bundle, pcm, sample_rate, session)
            self._metrics.record("asr", asr_ms)

            await emit(
                BaseMessage(
                    **base,
                    type="asr.partial",
                    sequence_no=self._next_seq(),
                    timestamp_ms=now_ms(),
                    is_final=False,
                    payload={
                        "text": partial_text,
                        "language": session.source_lang,
                        "language_probability": asr_result.get("language_probability", 0.0),
                        "confidence": asr_result.get("confidence", 0.0),
                        "start_ms": asr_result.get("start_ms", 0),
                        "end_ms": asr_result.get("end_ms", 0),
                        "stable": False,
                        "revision": 1,
                        "words": [],
                    },
                )
            )

            if self._sm.mark_asr_final(session.session_id, seg_id):
                await emit(
                    BaseMessage(
                        **base,
                        type="asr.final",
                        sequence_no=self._next_seq(),
                        timestamp_ms=now_ms(),
                        is_final=True,
                        latency_ms=asr_ms,
                        payload=asr_result,
                    )
                )

            if not partial_text:
                queue.complete(seg_id)
                return seg_id

            translated, mt_ms = self._run_translate(bundle, partial_text, session)
            self._metrics.record("translate", mt_ms)

            if self._sm.mark_translate(session.session_id, seg_id):
                await emit(
                    BaseMessage(
                        **base,
                        type="translate.result",
                        sequence_no=self._next_seq(),
                        timestamp_ms=now_ms(),
                        is_final=True,
                        latency_ms=mt_ms,
                        payload={"text": translated, "source_text": partial_text},
                    )
                )

            pcm_tts, sample_rate_tts, fmt, tts_ms = self._run_tts(bundle, translated, session)
            self._metrics.record("tts", tts_ms)

            await emit(
                BaseMessage(
                    **base,
                    type="tts.audio",
                    sequence_no=self._next_seq(),
                    timestamp_ms=now_ms(),
                    is_final=True,
                    latency_ms=tts_ms,
                    payload={
                        "sample_rate": sample_rate_tts,
                        "channels": 1,
                        "sample_format": fmt,
                        "duration_ms": int(pcm_tts.size / max(sample_rate_tts, 1) * 1000),
                        "payload_size": int(pcm_tts.size * 2),
                        "is_final": True,
                        "text": translated,
                        "voice_id": self._voice_for(session.target_lang),
                        "audio_bytes": pcm_tts.tobytes(),
                    },
                )
            )
            queue.complete(seg_id)
            return seg_id
        except ServiceError as exc:
            queue.drop(seg_id, "manual")
            await self._emit_dropped(emit, session, seg_id, exc.code.value, message=exc.message)
            return None
        except Exception as exc:  # pragma: no cover - defensive
            queue.drop(seg_id, "manual")
            log.exception("pipeline segment %s failed", seg_id)
            await self._emit_dropped(emit, session, seg_id, ErrorCode.INTERNAL_ERROR.value, message=str(exc))
            return None

    async def _emit_dropped(
        self,
        emit: Callable[[BaseMessage], Awaitable[None]],
        session: Any,
        seg_id: str,
        code: str,
        *,
        reason: str = "error",
        message: str = "",
    ) -> None:
        await emit(
            BaseMessage(
                session_id=session.session_id,
                stream_id=session.stream_id,
                direction=session.direction,
                segment_id=seg_id,
                source_lang=session.source_lang,
                target_lang=session.target_lang,
                protocol_version=PROTOCOL_VERSION,
                type="error",
                sequence_no=self._next_seq(),
                timestamp_ms=now_ms(),
                error_code=code,
                payload={"code": code, "reason": reason, "message": message, "segment_id": seg_id},
            )
        )

    @staticmethod
    def _run_asr(bundle: Any, pcm: np.ndarray, sample_rate: int, session: Any) -> tuple[str, dict, int]:
        t0 = time.perf_counter()
        result = bundle.asr.feed_segment(pcm, sample_rate=sample_rate, language=session.source_lang)
        ms = int((time.perf_counter() - t0) * 1000)
        return result.get("text", ""), result, ms

    @staticmethod
    def _run_translate(bundle: Any, text: str, session: Any) -> tuple[str, int]:
        t0 = time.perf_counter()
        translated = bundle.translate.translate(text, session.source_lang, session.target_lang)
        ms = int((time.perf_counter() - t0) * 1000)
        return translated, ms

    @staticmethod
    def _run_tts(bundle: Any, text: str, session: Any) -> tuple[np.ndarray, int, str, int]:
        voice_id = PipelineOrchestrator._voice_for(session.target_lang)
        t0 = time.perf_counter()
        pcm, sample_rate, fmt = bundle.tts.synth(text, voice_id)
        ms = int((time.perf_counter() - t0) * 1000)
        return pcm, sample_rate, fmt, ms

    _seq: int = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @staticmethod
    def _voice_for(lang: str) -> str:
        if lang.startswith("cmn"):
            return "mock-cmn"
        return "mock-eng"
