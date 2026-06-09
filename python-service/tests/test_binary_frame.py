"""Tests for the WebSocket binary frame codec."""

from __future__ import annotations

import pytest

from olb.runtime.binary_frame import decode_binary_frame, encode_binary_frame


def test_roundtrip_short_frame() -> None:
    header = {
        "protocol_version": "1.0",
        "type": "audio.frame",
        "session_id": "ses_test",
        "stream_id": "audio_local",
        "direction": "local_to_remote",
        "segment_id": "seg_test",
        "sequence_no": 1,
        "timestamp_ms": 1700000000000,
        "sample_rate": 16000,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "payload_size": 4,
    }
    payload = b"\x00\x01\x02\x03"
    blob = encode_binary_frame(header, payload)
    assert blob[:4] == b"OLB1"
    out_header, out_payload = decode_binary_frame(blob)
    assert out_header == header
    assert out_payload == payload


def test_bad_magic() -> None:
    with pytest.raises(ValueError):
        decode_binary_frame(b"OLB2" + b"\x00" * 16)


def test_short_frame() -> None:
    with pytest.raises(ValueError):
        decode_binary_frame(b"OLB1")


def test_rejects_oversized_frame() -> None:
    with pytest.raises(ValueError, match="frame too large"):
        decode_binary_frame(b"OLB1" + b"\x00" * 16, max_frame_bytes=4)


def test_rejects_oversized_header() -> None:
    blob = b"OLB1" + (5).to_bytes(4, "little") + b"{}"
    with pytest.raises(ValueError, match="header too large"):
        decode_binary_frame(blob, max_header_bytes=1)
