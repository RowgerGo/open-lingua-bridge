"""Tests for the pipeline orchestrator end-to-end with mock providers."""

from __future__ import annotations

import asyncio

import numpy as np

from olb.config import ServiceConfig
from olb.runtime.metrics import Metrics
from olb.runtime.model_manager import ModelManager
from olb.runtime.pipeline_orchestrator import PipelineOrchestrator
from olb.runtime.session_manager import SessionManager
from olb.schemas.protocol import BaseMessage


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_orchestrator_produces_asr_translate_tts() -> None:
    cfg = ServiceConfig.from_env()
    mm = ModelManager(cfg)
    sm = SessionManager()
    metrics = Metrics()
    orch = PipelineOrchestrator(mm, sm, metrics)
    sm.start(
        source_lang="cmn_Hans",
        target_lang="eng_Latn",
        direction="local_to_remote",
        stream_id="audio_local",
    )
    sid = list(sm._sessions.keys())[0]  # noqa: SLF001
    pcm = (np.random.default_rng(0).standard_normal(int(2.0 * 16000)) * 6000).astype(np.int16)
    pcm[: 16000 // 4] = 0
    pcm[-16000 // 4 :] = 0

    received: list[BaseMessage] = []

    async def emit(msg: BaseMessage) -> None:
        received.append(msg)

    segs = _run(orch.ingest_pcm(sid, pcm, 16000, 1, emitter=emit))
    assert segs
    types = [m.type for m in received]
    assert "asr.final" in types
    assert "translate.result" in types
    assert "tts.audio" in types
