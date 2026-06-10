"""Audio anomaly regression tests for binary frame validation."""

from __future__ import annotations

import pytest

from olb.runtime.binary_frame import decode_binary_frame, encode_binary_frame
from olb.runtime.e2e import synthetic_pcm_stream


def _header(payload: bytes, **overrides) -> dict:
    header = {
        "protocol_version": "1.0",
        "type": "audio.frame",
        "session_id": "ses_audio_anomaly",
        "stream_id": "audio_local",
        "direction": "local_to_remote",
        "segment_id": "seg_audio_anomaly",
        "sequence_no": 1,
        "timestamp_ms": 1_700_000_000_000,
        "sample_rate": 16_000,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "payload_size": len(payload),
    }
    header.update(overrides)
    return header


def test_payload_size_mismatch_is_rejected() -> None:
    payload = synthetic_pcm_stream(duration_ms=20)
    with pytest.raises(ValueError, match="payload_size mismatch"):
        decode_binary_frame(encode_binary_frame(_header(payload, payload_size=1), payload))


def test_truncated_header_is_rejected() -> None:
    with pytest.raises(ValueError, match="header truncated"):
        decode_binary_frame(b"OLB1" + (8).to_bytes(4, "little") + b"{}")


def test_oversized_header_is_rejected() -> None:
    with pytest.raises(ValueError, match="header too large"):
        decode_binary_frame(b"OLB1" + (2).to_bytes(4, "little") + b"{}", max_header_bytes=1)


def test_oversized_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="frame too large"):
        decode_binary_frame(b"OLB1" + b"\x00" * 16, max_frame_bytes=8)
