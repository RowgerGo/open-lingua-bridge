"""End-to-end driver that boots the Python Model Service in mock mode and drives the realtime WebSocket channel with synthetic audio frames."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python-service"))
from tests.fixtures import build_frame_packets, synth_speech_like_pcm  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_AUTH_TOKEN = "dev-token"
DEFAULT_PROTOCOL_VERSION = "1.0"


@dataclass
class E2EResult:
    host: str
    port: int
    health_ok: bool = False
    models_load_ok: bool = False
    chain_check_ok: bool = False
    session_started: bool = False
    segments_emitted: list[str] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    tts_frames: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_markdown(self) -> str:
        lines = [
            "# open-lingua-bridge E2E report",
            "",
            f"- Backend: `http://{self.host}:{self.port}`",
            f"- Health: {'OK' if self.health_ok else 'FAIL'}",
            f"- Models load: {'OK' if self.models_load_ok else 'FAIL'}",
            f"- Language chain: {'OK' if self.chain_check_ok else 'FAIL'}",
            f"- Session started: {'OK' if self.session_started else 'FAIL'}",
            f"- Segments emitted: {len(self.segments_emitted)}",
            f"- Translations: {len(self.translations)}",
            f"- TTS binary frames: {self.tts_frames}",
            f"- Duration: {self.duration_ms} ms",
            "",
        ]
        if self.errors:
            lines.append("## Errors")
            lines.append("")
            for err in self.errors:
                lines.append(f"- {err}")
            lines.append("")
        return "\n".join(lines)


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def boot_service(host: str, port: int, log_path: Path) -> subprocess.Popen:
    env_overrides = {
        "OLB_HOST": host,
        "OLB_PORT": str(port),
        "OLB_AUTH_TOKEN": DEFAULT_AUTH_TOKEN,
        "OLB_PROTOCOL_VERSION": DEFAULT_PROTOCOL_VERSION,
        "PYTHONUNBUFFERED": "1",
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "olb.app:build_app", "--factory", "--host", host, "--port", str(port)],
        cwd=str(ROOT / "python-service"),
        env={**os.environ, **env_overrides},
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    if not wait_for_port(host, port):
        proc.terminate()
        raise RuntimeError(f"service did not start on {host}:{port}; see {log_path}")
    return proc


async def run_e2e(host: str, port: int, *, report_path: Path) -> E2EResult:
    result = E2EResult(host=host, port=port)
    started = time.perf_counter()
    base = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/ws/session"
    headers = {
        "X-OLB-Auth-Token": DEFAULT_AUTH_TOKEN,
        "X-OLB-Protocol-Version": DEFAULT_PROTOCOL_VERSION,
        "X-OLB-Client": "e2e-runner",
    }

    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=10.0) as client:
        try:
            health = await client.get("/health")
            result.health_ok = health.status_code == 200 and health.json().get("success") is True
        except Exception as exc:
            result.errors.append(f"health: {exc}")

        try:
            load = await client.post(
                "/models/load",
                json={"providers": ["vad", "asr", "translate", "tts"], "config": {"mode": "mock"}},
            )
            result.models_load_ok = load.status_code == 200 and load.json().get("success") is True
        except Exception as exc:
            result.errors.append(f"models_load: {exc}")

        try:
            chain = await client.post(
                "/language-chain/check",
                json={"source_lang": "cmn_Hans", "target_lang": "eng_Latn", "require_tts": True},
            )
            result.chain_check_ok = chain.status_code == 200 and chain.json().get("success") is True
        except Exception as exc:
            result.errors.append(f"chain_check: {exc}")

    pcm = synth_speech_like_pcm()
    packets = build_frame_packets(pcm, segment_id="seg_e2e_1", session_id="ses_e2e")

    try:
        async with websockets.connect(ws_url, extra_headers={"X-OLB-Auth-Token": DEFAULT_AUTH_TOKEN}) as ws:
            await ws.send(
                json.dumps(
                    {
                        "protocol_version": DEFAULT_PROTOCOL_VERSION,
                        "type": "session.start",
                        "session_id": "ses_e2e",
                        "source_lang": "cmn_Hans",
                        "target_lang": "eng_Latn",
                        "direction": "local_to_remote",
                        "stream_id": "audio_local",
                    }
                )
            )
            ack = json.loads(await ws.recv())
            result.session_started = ack.get("type") == "status.update"

            for packet in packets:
                await ws.send(packet)

            expected_messages = max(3, len(packets))
            for _ in range(expected_messages):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    break
                if isinstance(raw, bytes):
                    if raw.startswith(b"OLB1"):
                        result.tts_frames += 1
                    continue
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "asr.partial":
                    seg = msg.get("segment_id")
                    if seg and seg not in result.segments_emitted:
                        result.segments_emitted.append(seg)
                elif mtype == "translate.result":
                    text = msg.get("payload", {}).get("text")
                    if text:
                        result.translations.append(text)
                elif mtype == "error":
                    result.errors.append(f"realtime error: {msg.get('error_code')} {msg.get('payload')}")
    except Exception as exc:
        result.errors.append(f"ws: {exc}")

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(result.to_markdown(), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="open-lingua-bridge E2E driver")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--auth-token", default=DEFAULT_AUTH_TOKEN)
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "e2e-report.md")
    parser.add_argument("--log", type=Path, default=ROOT / "target" / "e2e-service.log")
    parser.add_argument("--keep-service", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proc = boot_service(args.host, args.port, args.log)
    try:
        result = asyncio.run(run_e2e(args.host, args.port, report_path=args.report))
    finally:
        if not args.keep_service:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    print(result.to_markdown())
    ok = result.health_ok and result.models_load_ok and result.chain_check_ok and result.session_started
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())