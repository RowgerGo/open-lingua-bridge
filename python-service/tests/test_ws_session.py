"""WebSocket session tests for JSON text results and binary TTS audio."""

from __future__ import annotations

import json

import numpy as np
from fastapi.testclient import TestClient

from olb.app import build_app
from olb.config import ServiceConfig
from olb.runtime.binary_frame import decode_binary_frame, encode_binary_frame


def test_ws_session_roundtrips_text_results_and_binary_tts() -> None:
    cfg = ServiceConfig.from_env()
    app = build_app(cfg)
    pcm = (np.ones(int(1.0 * 16000)) * 6000).astype(np.int16)
    header = {
        "protocol_version": cfg.protocol_version,
        "type": "audio.frame",
        "session_id": "ses_ws_test",
        "stream_id": "audio_local",
        "direction": "local_to_remote",
        "segment_id": "seg_ws_test",
        "sequence_no": 1,
        "timestamp_ms": 1700000000000,
        "sample_rate": 16000,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "payload_size": pcm.nbytes,
    }

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/session",
            headers={"X-OLB-Auth-Token": cfg.auth_token},
        ) as ws:
            ws.send_text(
                json.dumps(
                    {
                        "protocol_version": cfg.protocol_version,
                        "type": "session.start",
                        "session_id": "ses_ws_test",
                        "source_lang": "cmn_Hans",
                        "target_lang": "eng_Latn",
                        "direction": "local_to_remote",
                        "stream_id": "audio_local",
                    }
                )
            )
            started = json.loads(ws.receive_text())
            assert started["type"] == "status.update"

            ws.send_bytes(encode_binary_frame(header, pcm.tobytes()))
            text_types: set[str] = set()
            binary_header = None
            binary_payload = b""
            for _ in range(6):
                message = ws.receive()
                if message.get("text") is not None:
                    data = json.loads(message["text"])
                    text_types.add(data["type"])
                elif message.get("bytes") is not None:
                    binary_header, binary_payload = decode_binary_frame(message["bytes"])
                    break

            assert {"asr.partial", "asr.final", "translate.result"}.issubset(text_types)
            assert binary_header is not None
            assert binary_header["type"] == "tts.audio"
            assert binary_header["payload"]["payload_size"] == len(binary_payload)
            assert binary_payload
