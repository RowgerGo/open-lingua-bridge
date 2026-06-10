from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

FIXTURE_DIR = Path(__file__).resolve().parent
SAMPLE_RATE = 16_000
DURATION_SECONDS = 1.0
CHANNELS = 1
SAMPLE_WIDTH = 2


def synth_speech_like_pcm(seed: int = 1337, duration: float = DURATION_SECONDS) -> np.ndarray:
    rng = np.random.default_rng(seed)
    total = int(SAMPLE_RATE * duration)
    samples = np.zeros(total, dtype=np.float32)
    frame = SAMPLE_RATE // 50
    for start in range(0, total, frame):
        if (start // frame) % 25 < 12:
            t = np.arange(frame, dtype=np.float32) / SAMPLE_RATE
            tone = 0.6 * np.sin(2 * np.pi * 440.0 * t + rng.normal(0.0, 0.05))
            envelope = np.linspace(0.4, 1.0, frame, dtype=np.float32)
            samples[start : start + frame] = tone * envelope
    pcm = np.clip(samples, -1.0, 1.0)
    return (pcm * 32767.0).astype(np.int16)


def write_wav(path: Path, pcm: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return path


SAMPLE_FIXTURE_PATH = FIXTURE_DIR / "mock_speech_16k_mono_s16le.wav"


def ensure_sample_fixture(path: Path = SAMPLE_FIXTURE_PATH) -> Path:
    if not path.exists():
        write_wav(path, synth_speech_like_pcm())
    return path


def build_frame_packets(pcm: np.ndarray, *, segment_id: str = "seg_e2e", session_id: str = "ses_e2e") -> list[bytes]:
    from olb.runtime.binary_frame import encode_binary_frame

    frame = SAMPLE_RATE // 50
    packets: list[bytes] = []
    for index, start in enumerate(range(0, len(pcm), frame)):
        chunk = pcm[start : start + frame]
        if chunk.size == 0:
            continue
        header = {
            "protocol_version": "1.0",
            "type": "audio.frame",
            "session_id": session_id,
            "stream_id": "audio_local",
            "direction": "local_to_remote",
            "segment_id": segment_id,
            "sequence_no": index + 1,
            "timestamp_ms": start * 1000 // SAMPLE_RATE,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_format": "pcm_s16le",
            "payload_size": chunk.nbytes,
        }
        packets.append(encode_binary_frame(header, chunk.tobytes()))
    return packets


def fixture_payload_size(payload: bytes) -> int:
    if len(payload) < 8 or payload[:4] != b"OLB1":
        raise ValueError("not an OLB1 frame")
    (header_len,) = struct.unpack("<I", payload[4:8])
    return len(payload) - 8 - header_len