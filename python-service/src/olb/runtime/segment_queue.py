"""Per-session segment queue with TTL and backpressure.

Each session has at most ``max_pending`` segments in flight. New segments
beyond the cap are dropped with the protocol code
``PLAYBACK_QUEUE_OVERLOADED`` and reported as ``segment_state='dropped'``.

A segment is considered stale if it has been queued longer than
``ttl_ms``; stale segments are expired and dropped with
``segment_state='expired'`` when ``evict_expired`` is called.

The queue is intentionally small: a slow ASR / MT / TTS pipeline should
surface backpressure to the caller rather than accumulate audio.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

SegmentDropReason = Literal["overloaded", "expired", "manual"]


@dataclass
class QueuedSegment:
    segment_id: str
    session_id: str
    queued_at_ms: int
    state: str = "queued"
    state_message: str = ""
    samples: int = 0


@dataclass
class SegmentQueueStats:
    queued: int = 0
    running: int = 0
    dropped_overloaded: int = 0
    dropped_expired: int = 0
    completed: int = 0


class SegmentQueue:
    """Per-session FIFO queue with TTL eviction and a hard pending cap."""

    def __init__(self, max_pending: int = 8, ttl_ms: int = 8_000) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")
        if ttl_ms < 1:
            raise ValueError("ttl_ms must be >= 1")
        self._max_pending = max_pending
        self._ttl_ms = ttl_ms
        self._lock = threading.Lock()
        self._items: dict[str, QueuedSegment] = {}
        self._stats = SegmentQueueStats()

    @property
    def max_pending(self) -> int:
        return self._max_pending

    @property
    def ttl_ms(self) -> int:
        return self._ttl_ms

    def stats(self) -> SegmentQueueStats:
        with self._lock:
            return SegmentQueueStats(
                queued=sum(1 for q in self._items.values() if q.state == "queued"),
                running=sum(1 for q in self._items.values() if q.state == "running"),
                dropped_overloaded=self._stats.dropped_overloaded,
                dropped_expired=self._stats.dropped_expired,
                completed=self._stats.completed,
            )

    def enqueue(
        self,
        session_id: str,
        segment_id: str,
        *,
        samples: int = 0,
    ) -> tuple[bool, str | None]:
        with self._lock:
            self._evict_expired_locked()
            pending = [q for q in self._items.values() if q.state in ("queued", "running")]
            if len(pending) >= self._max_pending:
                self._stats.dropped_overloaded += 1
                return False, "PLAYBACK_QUEUE_OVERLOADED"
            self._items[segment_id] = QueuedSegment(
                segment_id=segment_id,
                session_id=session_id,
                queued_at_ms=int(time.time() * 1000),
                state="queued",
                samples=samples,
            )
            self._stats.queued += 1
            return True, None

    def mark_running(self, segment_id: str) -> None:
        with self._lock:
            item = self._items.get(segment_id)
            if item is not None and item.state == "queued":
                item.state = "running"
                self._stats.queued = max(0, self._stats.queued - 1)
                self._stats.running += 1

    def complete(self, segment_id: str) -> None:
        with self._lock:
            item = self._items.pop(segment_id, None)
            if item is None:
                return
            if item.state == "running":
                self._stats.running = max(0, self._stats.running - 1)
            self._stats.completed += 1

    def drop(self, segment_id: str, reason: SegmentDropReason) -> None:
        with self._lock:
            item = self._items.pop(segment_id, None)
            if item is None:
                return
            if item.state == "queued":
                self._stats.queued = max(0, self._stats.queued - 1)
            elif item.state == "running":
                self._stats.running = max(0, self._stats.running - 1)
            if reason == "expired":
                self._stats.dropped_expired += 1
            elif reason == "overloaded":
                self._stats.dropped_overloaded += 1

    def evict_expired(self) -> list[str]:
        with self._lock:
            return self._evict_expired_locked()

    def _evict_expired_locked(self) -> list[str]:
        now_ms = int(time.time() * 1000)
        expired: list[str] = []
        for sid, item in list(self._items.items()):
            if now_ms - item.queued_at_ms > self._ttl_ms:
                expired.append(sid)
                self._items.pop(sid, None)
                if item.state == "queued":
                    self._stats.queued = max(0, self._stats.queued - 1)
                elif item.state == "running":
                    self._stats.running = max(0, self._stats.running - 1)
                self._stats.dropped_expired += 1
        return expired


@dataclass
class SegmentQueueRegistry:
    """Manages per-session queues with a shared capacity policy."""

    max_pending: int = 8
    ttl_ms: int = 8_000
    _queues: dict[str, SegmentQueue] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def for_session(self, session_id: str) -> SegmentQueue:
        with self._lock:
            q = self._queues.get(session_id)
            if q is None:
                q = SegmentQueue(max_pending=self.max_pending, ttl_ms=self.ttl_ms)
                self._queues[session_id] = q
            return q

    def drop_session(self, session_id: str) -> None:
        with self._lock:
            self._queues.pop(session_id, None)

    def evict_expired_all(self) -> dict[str, list[str]]:
        with self._lock:
            return {sid: q.evict_expired() for sid, q in self._queues.items()}
