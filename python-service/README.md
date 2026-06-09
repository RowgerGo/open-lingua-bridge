# open-lingua-bridge Python Model Service

Local HTTP + WebSocket service that hosts the VAD / ASR / translation / TTS
pipeline used by the Rust Core.

## Quick start (mock pipeline)

```bash
cd python-service
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[test]"
olb-model-service --port 8765
```

The service binds to `127.0.0.1:8765` and exposes:

- `GET  /health`
- `GET  /models`
- `GET  /voices`
- `POST /models/load`
- `POST /models/warmup`
- `POST /language-chain/check`
- `POST /core/session/precheck`
- `POST /backend/session/start`
- `POST /backend/session/stop`
- `POST /test/asr`
- `POST /test/translate`
- `POST /test/tts`
- `WS   /ws/session`

## Real model providers

```bash
pip install -e ".[real]"
olb-model-service --port 8765
```

The model service then loads:

- `silero-vad` for VAD
- `faster-whisper` for ASR
- NLLB via `transformers` for translation
- Piper for TTS
