"""WebSocket protocol error coverage for malformed JSON and binary frames."""

from __future__ import annotations

import json
import struct

import pytest
from fastapi.testclient import TestClient

from olb.app import build_app
from olb.config import ServiceConfig
from olb.runtime.binary_frame import encode_binary_frame
from olb.runtime.e2e import SAMPLE_RATE, synthetic_pcm_stream


def _client() -> tuple[ServiceConfig, TestClient]:
    cfg = ServiceConfig.from_env()
    return cfg, TestClient(build_app(cfg))


def _start(ws, cfg: ServiceConfig, session_id: str = "ses_ws_errors") -> None:
    ws.send_text(
        json.dumps(
            {
                "protocol_version": cfg.protocol_version,
                "type": "session.start",
                "session_id": session_id,
                "source_lang": "cmn_Hans",
                "target_lang": "eng_Latn",
                "direction": "local_to_remote",
                "stream_id": "audio_local",
            }
        )
    )
    assert json.loads(ws.receive_text())["type"] == "status.update"


def _header(cfg: ServiceConfig, payload: bytes, **overrides) -> dict:
    header = {
        "protocol_version": cfg.protocol_version,
        "type": "audio.frame",
        "session_id": "ses_ws_errors",
        "stream_id": "audio_local",
        "direction": "local_to_remote",
        "segment_id": "seg_ws_errors",
        "sequence_no": 1,
        "timestamp_ms": 1_700_000_000_000,
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "payload_size": len(payload),
    }
    header.update(overrides)
    return header


def _error_for_binary(blob: bytes, *, start_session: bool = True) -> dict:
    cfg, client = _client()
    with client:
        with client.websocket_connect("/ws/session", headers={"X-OLB-Auth-Token": cfg.auth_token}) as ws:
            if start_session:
                _start(ws, cfg)
            ws.send_bytes(blob)
            return json.loads(ws.receive_text())


def _error_for_binary_with_cfg(blob: bytes, cfg: ServiceConfig) -> dict:
    with TestClient(build_app(cfg)) as client:
        with client.websocket_connect("/ws/session", headers={"X-OLB-Auth-Token": cfg.auth_token}) as ws:
            _start(ws, cfg)
            ws.send_bytes(blob)
            return json.loads(ws.receive_text())


@pytest.mark.parametrize(
    ("blob", "message_part"),
    [
        (b"OLB2" + b"\x00" * 8, "bad magic"),
        (b"OLB1" + struct.pack("<I", 65_537) + b"{}", "header too large"),
        (b"OLB1" + struct.pack("<I", 8) + b"{}", "header truncated"),
    ],
)
def test_binary_decode_errors_return_invalid_request(blob: bytes, message_part: str) -> None:
    error = _error_for_binary(blob)
    assert error["error_code"] == "INVALID_REQUEST"
    assert message_part in error["payload"]["message"]


def test_oversized_frame_returns_invalid_request() -> None:
    cfg = ServiceConfig.from_env()
    cfg.max_binary_frame_bytes = 8
    error = _error_for_binary_with_cfg(b"OLB1" + b"\x00" * 32, cfg)
    assert error["error_code"] == "INVALID_REQUEST"
    assert "frame too large" in error["payload"]["message"]


def test_payload_size_mismatch_returns_invalid_request() -> None:
    cfg = ServiceConfig.from_env()
    payload = synthetic_pcm_stream(duration_ms=20)
    blob = encode_binary_frame(_header(cfg, payload, payload_size=len(payload) + 1), payload)
    error = _error_for_binary(blob)
    assert error["error_code"] == "INVALID_REQUEST"
    assert "payload_size mismatch" in error["payload"]["message"]


def test_protocol_version_mismatch_returns_invalid_request_for_binary() -> None:
    cfg = ServiceConfig.from_env()
    payload = synthetic_pcm_stream(duration_ms=20)
    blob = encode_binary_frame(_header(cfg, payload, protocol_version="9.9"), payload)
    error = _error_for_binary(blob)
    assert error["error_code"] == "PROTOCOL_VERSION_MISMATCH"


def test_unknown_json_message_type_returns_invalid_request() -> None:
    cfg, client = _client()
    with client:
        with client.websocket_connect("/ws/session", headers={"X-OLB-Auth-Token": cfg.auth_token}) as ws:
            ws.send_text(json.dumps({"protocol_version": cfg.protocol_version, "type": "unknown.event", "session_id": "ses_unknown"}))
            error = json.loads(ws.receive_text())
    assert error["error_code"] == "INVALID_REQUEST"


def test_missing_session_id_returns_session_not_found_for_binary() -> None:
    cfg = ServiceConfig.from_env()
    payload = synthetic_pcm_stream(duration_ms=20)
    blob = encode_binary_frame(_header(cfg, payload, session_id=""), payload)
    error = _error_for_binary(blob, start_session=False)
    assert error["error_code"] == "SESSION_NOT_FOUND"


def test_bad_auth_token_closes_ws() -> None:
    cfg, client = _client()
    with client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/session", headers={"X-OLB-Auth-Token": cfg.auth_token + "-bad"}):
                pass


def test_binary_frame_must_be_audio_frame() -> None:
    cfg = ServiceConfig.from_env()
    payload = synthetic_pcm_stream(duration_ms=20)
    blob = encode_binary_frame(_header(cfg, payload, type="tts.audio"), payload)
    error = _error_for_binary(blob)
    assert error["error_code"] == "INVALID_REQUEST"
    assert "audio.frame" in error["payload"]["message"]
