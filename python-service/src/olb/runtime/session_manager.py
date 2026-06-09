"""Session manager: tracks active sessions and the per-session ASR state."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from ..schemas.protocol import new_id


@dataclass
class SessionState:
    session_id: str
    source_lang: str
    target_lang: str
    direction: str
    stream_id: str
    state: str = "running"
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    seen_segments: set[str] = field(default_factory=set)
    asr_final_locked: set[str] = field(default_factory=set)
    translate_locked: set[str] = field(default_factory=set)

    def next_segment_id(self) -> str:
        sid = f"seg_{uuid.uuid4().hex[:12]}"
        self.seen_segments.add(sid)
        return sid


class SessionManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}

    def start(
        self,
        source_lang: str,
        target_lang: str,
        direction: str,
        stream_id: str,
        session_id: str | None = None,
    ) -> SessionState:
        with self._lock:
            sid = session_id or new_id("ses")
            if sid in self._sessions:
                raise KeyError(f"session {sid} already exists")
            state = SessionState(
                session_id=sid,
                source_lang=source_lang,
                target_lang=target_lang,
                direction=direction,
                stream_id=stream_id,
            )
            self._sessions[sid] = state
            return state

    def get(self, session_id: str) -> SessionState:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def stop(self, session_id: str, flush: bool = True) -> SessionState:
        with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is None:
                raise KeyError(session_id)
            state.state = "stopped" if flush else "cancelled"
            return state

    def mark_asr_final(self, session_id: str, segment_id: str) -> bool:
        """Return True if this is the first ``asr.final`` for the segment."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise KeyError(session_id)
            if segment_id in state.asr_final_locked:
                return False
            state.asr_final_locked.add(segment_id)
            return True

    def mark_translate(self, session_id: str, segment_id: str) -> bool:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise KeyError(session_id)
            if segment_id in state.translate_locked:
                return False
            state.translate_locked.add(segment_id)
            return True

    def list(self) -> list[SessionState]:
        with self._lock:
            return list(self._sessions.values())
