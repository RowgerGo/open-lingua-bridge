"""Pydantic schemas that mirror the realtime protocol and HTTP envelopes."""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Match the protocol version declared by Rust Core and the docs.
PROTOCOL_VERSION = "1.0"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Generic envelope
# ---------------------------------------------------------------------------


class Envelope(BaseModel):
    """The standard HTTP response envelope used by all control APIs."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    code: str = "OK"
    message: str = ""
    data: Optional[Any] = None
    request_id: str = Field(default_factory=lambda: new_id("req"))
    protocol_version: str = PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Realtime protocol envelopes (WebSocket text JSON)
# ---------------------------------------------------------------------------


class BaseMessage(BaseModel):
    """Common header for every realtime text/binary envelope."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol_version: str = PROTOCOL_VERSION
    type: str
    session_id: str
    stream_id: Optional[str] = None
    direction: Optional[Literal["local_to_remote", "remote_to_local"]] = None
    segment_id: Optional[str] = None
    sequence_no: int
    timestamp_ms: int = Field(default_factory=now_ms)
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    is_final: Optional[bool] = None
    latency_ms: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None


# ---------------------------------------------------------------------------
# HTTP control request schemas
# ---------------------------------------------------------------------------


class PrecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_lang: str
    target_lang: str
    require_tts: bool = True
    devices: dict[str, str] = Field(default_factory=dict)


class LanguageChainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_lang: str
    target_lang: str
    require_tts: bool = True


class ModelsLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[str]
    config: dict[str, Any] = Field(default_factory=dict)


class ModelsWarmupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[str] = Field(default_factory=list)


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = None
    source_lang: str
    target_lang: str
    direction: Literal["local_to_remote", "remote_to_local"] = "local_to_remote"
    stream_id: str = "audio_local"


class SessionStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    flush: bool = True


class TestAsrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_file_path: str
    language: str = "auto"


class TestTranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    source_lang: str
    target_lang: str


class TestTtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    language: str
    voice_id: str
    write_file: bool = False
