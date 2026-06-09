"""WebSocket realtime endpoint that consumes the binary audio protocol.

Rust Core connects here as the client. The server multiplexes many sessions
over the same socket by inspecting ``session_id`` in each frame header.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .binary_frame import decode_binary_frame, encode_binary_frame
from .model_manager import ModelManager
from .pipeline_orchestrator import PipelineOrchestrator
from .session_manager import SessionManager
from ..config import ServiceConfig
from ..schemas.protocol import BaseMessage, PROTOCOL_VERSION, new_id, now_ms

log = logging.getLogger("olb.ws")


def make_ws_router(
    cfg: ServiceConfig,
    mm: ModelManager,
    sm: SessionManager,
    orchestrator: PipelineOrchestrator,
) -> APIRouter:
    router = APIRouter()
    _uplink_seq: dict[str, int] = {}

    def _next_seq(session_id: str) -> int:
        _uplink_seq[session_id] = _uplink_seq.get(session_id, 0) + 1
        return _uplink_seq[session_id]

    @router.websocket("/ws/session")
    async def ws_session(ws: WebSocket) -> None:
        token = ws.headers.get("x-olb-auth-token")
        if token != cfg.auth_token:
            await ws.close(code=4401)
            return
        await ws.accept()
        peer = f"{ws.client.host}:{ws.client.port}" if ws.client else "?"
        log.info("ws connected from %s protocol=%s", peer, cfg.protocol_version)
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await _handle_text(ws, msg["text"], mm, sm, _next_seq)
                elif msg.get("bytes") is not None:
                    await _handle_binary(ws, msg["bytes"], cfg, mm, sm, orchestrator, _next_seq)
        except WebSocketDisconnect:
            log.info("ws disconnected peer=%s", peer)
        except Exception:
            log.exception("ws loop crashed peer=%s", peer)

    async def _handle_text(
        ws: WebSocket,
        raw: str,
        mm: ModelManager,
        sm: SessionManager,
        seq: Any,
    ) -> None:
        import json

        try:
            data = json.loads(raw)
        except Exception:
            await _send_error(ws, code="INVALID_REQUEST", message="bad json", seq=seq)
            return
        mtype = data.get("type")
        sid = data.get("session_id")
        if data.get("protocol_version") and data["protocol_version"] != PROTOCOL_VERSION:
            await _send_error(ws, code="PROTOCOL_VERSION_MISMATCH", message="protocol mismatch", seq=seq)
            return
        if mtype == "session.start":
            sm.start(
                source_lang=data["source_lang"],
                target_lang=data["target_lang"],
                direction=data.get("direction", "local_to_remote"),
                stream_id=data.get("stream_id", "audio_local"),
                session_id=sid,
            )
            await _send_text(
                ws,
                BaseMessage(
                    session_id=sid or "unknown",
                    type="status.update",
                    sequence_no=seq(sid or "unknown"),
                    timestamp_ms=now_ms(),
                    payload={"session_state": "running", "backend_state": "ready", "models": mm.list_models()},
                ),
            )
        elif mtype == "session.stop":
            try:
                sm.stop(sid, flush=data.get("flush", True))
            except KeyError:
                await _send_error(ws, code="SESSION_NOT_FOUND", message=sid, seq=seq)

    async def _handle_binary(
        ws: WebSocket,
        blob: bytes,
        cfg: ServiceConfig,
        mm: ModelManager,
        sm: SessionManager,
        orchestrator: PipelineOrchestrator,
        seq: Any,
    ) -> None:
        try:
            header, payload = decode_binary_frame(
                blob,
                max_frame_bytes=cfg.max_binary_frame_bytes,
                max_header_bytes=cfg.max_binary_header_bytes,
            )
        except Exception as exc:
            await _send_error(ws, code="INVALID_REQUEST", message=f"bad binary frame: {exc}", seq=seq)
            return
        if header.get("type") != "audio.frame":
            await _send_error(ws, code="INVALID_REQUEST", message="binary must be audio.frame", seq=seq)
            return
        sid = header["session_id"]
        try:
            sm.get(sid)
        except KeyError:
            await _send_error(ws, code="SESSION_NOT_FOUND", message=sid, seq=seq)
            return
        pcm = np.frombuffer(payload, dtype=np.int16)
        sample_rate = int(header.get("sample_rate", 16000))
        channels = int(header.get("channels", 1))

        async def emit(message: BaseMessage) -> None:
            if message.type != "tts.audio":
                await _send_text(ws, message)
                return
            data = message.model_dump()
            payload = data["payload"].pop("audio_bytes", b"")
            blob_out = encode_binary_frame(data, payload)
            await ws.send_bytes(blob_out)

        await orchestrator.ingest_pcm(sid, pcm, sample_rate, channels, emitter=emit)

    async def _send_text(ws: WebSocket, msg: BaseMessage) -> None:
        await ws.send_text(msg.model_dump_json())

    async def _send_error(ws: WebSocket, code: str, message: str, seq: Any) -> None:
        msg = BaseMessage(
            session_id="",
            type="error",
            sequence_no=0,
            timestamp_ms=now_ms(),
            error_code=code,
            payload={"code": code, "message": message, "recoverable": True},
        )
        await ws.send_text(msg.model_dump_json())

    return router
