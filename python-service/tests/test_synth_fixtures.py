from __future__ import annotations

import wave

import numpy as np

from tests.fixtures import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    SAMPLE_FIXTURE_PATH,
    build_frame_packets,
    ensure_sample_fixture,
    fixture_payload_size,
    synth_speech_like_pcm,
    write_wav,
)


def test_synth_speech_like_pcm_is_deterministic() -> None:
    a = synth_speech_like_pcm()
    b = synth_speech_like_pcm()
    assert a.dtype == np.int16
    assert a.shape == b.shape
    assert np.array_equal(a, b)
    assert a.size == SAMPLE_RATE
    assert np.any(a != 0)


def test_synth_speech_like_pcm_respects_duration() -> None:
    pcm = synth_speech_like_pcm(duration=0.25)
    assert pcm.size == SAMPLE_RATE // 4


def test_write_wav_round_trips_int16_mono() -> None:
    pcm = synth_speech_like_pcm()
    target = SAMPLE_FIXTURE_PATH.with_name("tmp_round_trip.wav")
    write_wav(target, pcm)
    try:
        with wave.open(str(target), "rb") as wav:
            assert wav.getnchannels() == CHANNELS
            assert wav.getsampwidth() == SAMPLE_WIDTH
            assert wav.getframerate() == SAMPLE_RATE
            frames = wav.readframes(wav.getnframes())
        decoded = np.frombuffer(frames, dtype=np.int16)
        assert np.array_equal(decoded, pcm)
    finally:
        target.unlink(missing_ok=True)


def test_ensure_sample_fixture_creates_canonical_file() -> None:
    fixture = ensure_sample_fixture()
    assert fixture.exists()
    assert fixture.suffix == ".wav"
    with wave.open(str(fixture), "rb") as wav:
        assert wav.getnchannels() == CHANNELS
        assert wav.getframerate() == SAMPLE_RATE


def test_build_frame_packets_round_trip_payload_size() -> None:
    pcm = synth_speech_like_pcm()
    packets = build_frame_packets(pcm)
    assert packets, "expected at least one packet"
    assert all(packet.startswith(b"OLB1") for packet in packets)
    assert fixture_payload_size(packets[0]) > 0


def test_fixture_payload_size_rejects_non_olb1() -> None:
    try:
        fixture_payload_size(b"not-a-frame")
    except ValueError as exc:
        assert "OLB1" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-OLB1 frame")