"""Tests for the P4 segment queue with TTL and backpressure."""

from __future__ import annotations

import time

import pytest

from olb.runtime.segment_queue import SegmentQueue, SegmentQueueRegistry


def test_segment_queue_enqueues_and_completes() -> None:
    q = SegmentQueue(max_pending=4, ttl_ms=8_000)
    ok, _ = q.enqueue("ses_a", "seg_001")
    assert ok
    stats = q.stats()
    assert stats.queued == 1
    q.mark_running("seg_001")
    assert q.stats().running == 1
    q.complete("seg_001")
    assert q.stats().completed == 1


def test_segment_queue_drops_when_overloaded() -> None:
    q = SegmentQueue(max_pending=2, ttl_ms=8_000)
    assert q.enqueue("ses_a", "seg_001")[0]
    assert q.enqueue("ses_a", "seg_002")[0]
    ok, code = q.enqueue("ses_a", "seg_003")
    assert not ok
    assert code == "PLAYBACK_QUEUE_OVERLOADED"
    assert q.stats().dropped_overloaded == 1


def test_segment_queue_evicts_expired() -> None:
    q = SegmentQueue(max_pending=8, ttl_ms=50)
    assert q.enqueue("ses_a", "seg_old")[0]
    time.sleep(0.08)
    evicted = q.evict_expired()
    assert evicted == ["seg_old"]
    assert q.stats().dropped_expired == 1


def test_segment_queue_rejects_invalid_construction() -> None:
    with pytest.raises(ValueError):
        SegmentQueue(max_pending=0, ttl_ms=8_000)
    with pytest.raises(ValueError):
        SegmentQueue(max_pending=4, ttl_ms=0)


def test_segment_queue_registry_isolates_sessions() -> None:
    reg = SegmentQueueRegistry(max_pending=2, ttl_ms=8_000)
    q1 = reg.for_session("ses_a")
    q2 = reg.for_session("ses_b")
    assert q1 is not q2
    assert q1.enqueue("ses_a", "seg_1")[0]
    assert q1.enqueue("ses_a", "seg_2")[0]
    assert not q1.enqueue("ses_a", "seg_3")[0]
    assert q2.enqueue("ses_b", "seg_1")[0]
    reg.drop_session("ses_a")
    assert reg.for_session("ses_a") is not q1
