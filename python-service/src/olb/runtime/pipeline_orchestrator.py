"""Pipeline orchestrator wires VAD -> ASR -> translate -> TTS together."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np

from ..schemas.protocol import BaseMessage, PROTOCOL_VERSION, now_ms
from .metrics import Metrics
from .model_manager import ModelManager
from .session_manager import SessionManager


EmitFn = Callable[[BaseMessage], Awaitable[None]]


@dataclass
class PipelineConfig:
    source_lang: str
    target_lang: str
    direction: str
    stream_id: str
    sample_rate: int = 16000


class PipelineOrchestrator:
    def __init__(
        self,
        model_manager: ModelManager,
        session_manager: SessionManager,
        metrics: Metrics,
    ) -> None:
        self._mm = model_manager
        self._sm = session_manager
        self._metrics = metrics
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def metrics(self) -> Metrics:
        return self._metrics

    def _emit(self, emitter: EmitFn | None) -> Callable[[BaseMessage], Awaitable[None]]:
        if emitter is None:  # used by tests that don't have a transport
            async def _drop(_msg: BaseMessage) -> None:  # pragma: no cover
                return None

            return _drop
        return emitter

    async def ingest_pcm(
        self,
        session_id: str,
        pcm: np.ndarray,
        sample_rate: int,
        channels: int = 1,
        emitter: EmitFn | None = None,
    ) -> list[str]:
        session = self._sm.get(session_id)
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        if pcm.dtype != np.int16:
            pcm = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
        if sample_rate != 16000:
            from scipy.signal import resample_poly

            ratio = 16000 / sample_rate
            pcm = resample_poly(pcm, 1, int(round(1 / ratio))).astype(np.int16)
        bundle = self._mm.bundle
        bundle.vad.reset()
        segments = bundle.vad.push_pcm(pcm, sample_rate=16000)
        segments += bundle.vad.flush()
        out: list[str] = []
        for seg in segments:
            out.append(await self._run_segment(session, seg["samples"], 16000, emitter))
        return out

    async def _run_segment(
        self,
        session,
        pcm: np.ndarray,
        sample_rate: int,
        emitter: EmitFn | None,
    ) -> str:
        bundle = self._mm.bundle
        emit = self._emit(emitter)
        seg_id = session.next_segment_id()
        base = {
            "session_id": session.session_id,
            "stream_id": session.stream_id,
            "direction": session.direction,
            "segment_id": seg_id,
            "source_lang": session.source_lang,
            "target_lang": session.target_lang,
            "protocol_version": PROTOCOL_VERSION,
        }
        partial_text = ""

        async def _asr_partial(text: str, revision: int) -> None:
            await emit(
                BaseMessage(
                    **base,
                    type="asr.partial",
                    sequence_no=self._next_seq(),
                    timestamp_ms=now_ms(),
                    is_final=False,
                    payload={
                        "text": text,
                        "language": session.source_lang,
                        "language_probability": 0.95,
                        "confidence": 0.9,
                        "start_ms": 0,
                        "end_ms": int(pcm.size / 16),
                        "stable": False,
                        "revision": revision,
                        "words": [],
                    },
                )
            )

        t0 = time.perf_counter()
        asr_result = bundle.asr.feed_segment(pcm, sample_rate=sample_rate, language=session.source_lang)
        asr_ms = int((time.perf_counter() - t0) * 1000)
        self._metrics.record("asr", asr_ms)
        self._metrics.asr_queue_size = max(0, self._metrics.asr_queue_size - 1)
        partial_text = asr_result.get("text", "")
        await _asr_partial(partial_text, 1)

        accepted = self._sm.mark_asr_final(session.session_id, seg_id)
        if accepted:
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
            return seg_id

        t0 = time.perf_counter()
        translated = bundle.translate.translate(partial_text, session.source_lang, session.target_lang)
        mt_ms = int((time.perf_counter() - t0) * 1000)
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

        self._metrics.tts_queue_size += 1
        t0 = time.perf_counter()
        pcm_tts, sample_rate_tts, fmt = bundle.tts.synth(translated, self._voice_for(session.target_lang))
        tts_ms = int((time.perf_counter() - t0) * 1000)
        self._metrics.tts_queue_size = max(0, self._metrics.tts_queue_size - 1)
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
        return seg_id

    _seq: int = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _voice_for(self, lang: str) -> str:
        return "mock-cmn" if lang.startswith("cmn") else "mock-eng"
