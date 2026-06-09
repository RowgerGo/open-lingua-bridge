"""Process-wide configuration loaded from environment variables and CLI flags."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelPaths:
    asr: str = ""
    vad: str = ""
    translate: str = ""
    tts_voice_dir: str = ""


@dataclass
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    auth_token: str = "dev-token"
    protocol_version: str = "1.0"
    max_binary_frame_bytes: int = 8 * 1024 * 1024
    max_binary_header_bytes: int = 64 * 1024
    model_paths: ModelPaths = field(default_factory=ModelPaths)
    data_dir: Path = field(default_factory=lambda: Path("./data"))

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        cfg = cls()
        cfg.host = os.environ.get("OLB_HOST", cfg.host)
        cfg.port = int(os.environ.get("OLB_PORT", str(cfg.port)))
        cfg.log_level = os.environ.get("OLB_LOG_LEVEL", cfg.log_level).upper()
        cfg.auth_token = os.environ.get("OLB_AUTH_TOKEN", cfg.auth_token)
        cfg.protocol_version = os.environ.get(
            "OLB_PROTOCOL_VERSION", cfg.protocol_version
        )
        cfg.max_binary_frame_bytes = int(
            os.environ.get("OLB_MAX_BINARY_FRAME_BYTES", str(cfg.max_binary_frame_bytes))
        )
        cfg.max_binary_header_bytes = int(
            os.environ.get("OLB_MAX_BINARY_HEADER_BYTES", str(cfg.max_binary_header_bytes))
        )
        cfg.data_dir = Path(os.environ.get("OLB_DATA_DIR", cfg.data_dir))
        cfg.model_paths.asr = os.environ.get("OLB_MODEL_ASR", "")
        cfg.model_paths.vad = os.environ.get("OLB_MODEL_VAD", "")
        cfg.model_paths.translate = os.environ.get("OLB_MODEL_TRANSLATE", "")
        cfg.model_paths.tts_voice_dir = os.environ.get("OLB_MODEL_TTS_DIR", "")
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        return cfg
