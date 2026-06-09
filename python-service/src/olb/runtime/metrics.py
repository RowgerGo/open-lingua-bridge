"""In-memory process metrics for the orchestrator and HTTP diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Metrics:
    asr_queue_size: int = 0
    translate_queue_size: int = 0
    tts_queue_size: int = 0
    last_asr_latency_ms: int = 0
    last_translate_latency_ms: int = 0
    last_tts_latency_ms: int = 0
    last_error: str | None = None
    _history: deque[tuple[str, int]] = field(default_factory=lambda: deque(maxlen=128))
    _lock: Lock = field(default_factory=Lock)

    def record(self, stage: str, latency_ms: int) -> None:
        with self._lock:
            if stage == "asr":
                self.last_asr_latency_ms = latency_ms
            elif stage == "translate":
                self.last_translate_latency_ms = latency_ms
            elif stage == "tts":
                self.last_tts_latency_ms = latency_ms
            self._history.append((stage, latency_ms))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "asr_queue_size": self.asr_queue_size,
                "translate_queue_size": self.translate_queue_size,
                "tts_queue_size": self.tts_queue_size,
                "last_asr_latency_ms": self.last_asr_latency_ms,
                "last_translate_latency_ms": self.last_translate_latency_ms,
                "last_tts_latency_ms": self.last_tts_latency_ms,
                "last_error": self.last_error,
                "history_size": len(self._history),
            }
