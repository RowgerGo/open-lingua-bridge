"""WebSocket binary frame codec used by both Rust Core and Python service.

Layout (little-endian):

    bytes 0..3   magic: ASCII "OLB1"
    bytes 4..7   header_len: u32le
    bytes 8..N   header_json: UTF-8 JSON object
    bytes N..end payload: PCM/WAV bytes

The codec is the canonical reference used by Rust unit tests in
``crates/olb-protocol`` and Python unit tests in ``python-service/tests``.
"""

from __future__ import annotations

import json
import struct
from typing import Any

MAGIC = b"OLB1"
HEADER = struct.Struct("<I")
DEFAULT_MAX_FRAME_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_HEADER_BYTES = 64 * 1024


def encode_binary_frame(header: dict[str, Any], payload: bytes) -> bytes:
    body = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return MAGIC + HEADER.pack(len(body)) + body + payload


def decode_binary_frame(
    blob: bytes,
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
) -> tuple[dict[str, Any], bytes]:
    if len(blob) > max_frame_bytes:
        raise ValueError("frame too large")
    if len(blob) < 8:
        raise ValueError("frame too short")
    if blob[:4] != MAGIC:
        raise ValueError("bad magic")
    (header_len,) = HEADER.unpack(blob[4:8])
    if header_len > max_header_bytes:
        raise ValueError("header too large")
    if len(blob) < 8 + header_len:
        raise ValueError("header truncated")
    header = json.loads(blob[8 : 8 + header_len].decode("utf-8"))
    payload = blob[8 + header_len :]
    expected = header.get("payload_size")
    if expected is not None and int(expected) != len(payload):
        raise ValueError("payload_size mismatch")
    return header, payload
