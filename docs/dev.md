# 本地开发命令

本文记录 P0 到 P5 落地后的最小开发与验证命令。

## Python Model Service

```bash
cd python-service
uv run --extra test pytest
uv run olb-model-service --port 8765
```

服务默认监听 `127.0.0.1:8765`，控制 API 只使用 `GET` 和 `POST`，实时通道为 `WS /ws/session`。

P4 在 mock provider 之外实现了本地真实模型：

- VAD：`SileroVadProvider`（onnxruntime 本地 ONNX 路径），`EnergyVadProvider` 是 mock/缺依赖时的能量阈值 fallback。
- ASR：`FasterWhisperProvider`（CTranslate2 Whisper），`MockAsrProvider` 用于测试和默认模式。
- 翻译：`NllbTranslateProvider`（Hugging Face `transformers`），`DictionaryTranslateProvider` / `MockTranslateProvider` 是 mock。
- TTS：`PiperTtsProvider`（onnxruntime Piper voice 目录），`MockTtsProvider` 是 mock。

安装可选依赖（按角色细分）：

```bash
pip install -e ".[vad]"        # silero-vad / onnxruntime
pip install -e ".[asr]"        # faster-whisper
pip install -e ".[translate]"  # transformers + sentencepiece + torch
pip install -e ".[tts]"        # piper-tts + onnxruntime
pip install -e ".[real]"       # 上述四项合一
```

模型文件需本地存在，路径通过 `POST /models/load` 的 `config.vad.model_path` / `asr.model_path` / `translate.model_path` / `tts.voice_path` 传入；缺文件时返回 `MODEL_FILE_MISSING`。`POST /language-chain/check` 走 `olb.providers.language.chain_check` 做 FLORES ↔ Whisper ↔ Piper 三方映射校验，链路不完整返回 `LANGUAGE_CHAIN_INCOMPLETE`。P4-08 的 `SegmentQueueRegistry` 提供 per-session `max_pending` + `ttl_ms`，超限和过期段会以 `PLAYBACK_QUEUE_OVERLOADED` / 过期事件回报。

## Rust Core / Protocol

```bash
cargo test
```

Rust workspace 当前包含：

- `crates/olb-protocol`：协议版本、错误码、消息结构、`OLB1` binary frame codec。
- `crates/olb-core`：配置、会话状态机、Python Model Service HTTP client、P2 mock WebSocket realtime smoke test client，以及 P3 音频设备枚举、采集、重采样、分帧、分段和 TTS 播放队列。
- `apps/desktop/src-tauri`：Tauri v2 桌面应用 Rust 入口与 `get_status`、`get_config`、`get_audio_devices`、`update_config`、`start_session`、`start_audio_session`、`pause_session`、`resume_session`、`stop_session` commands；`start_session` 会检查 Python health，连接 `WS /ws/session`，发送固定 mock PCM binary frame，等待 mock ASR/翻译/TTS smoke test 结果，并把带扁平化 `payload` 的 `RealtimeEvent` emit 到 UI。`start_audio_session` 会采集本方麦克风和可选对方输入设备，转换为 16 kHz mono `pcm_s16le`，按 `audio.frame` binary frame 发送给 Python，并将返回的 `tts.audio` 排队播放到选定输出设备。

Rust/Python 测试包含 `WS /ws/session` mock roundtrip：ASR/翻译结果通过 WebSocket text JSON 返回，`tts.audio` 通过 `OLB1` binary frame 返回。

## Tauri Desktop

```bash
cd apps/desktop
npm install
npm run tauri dev
```

桌面端提供 P5 工作台：显示后端状态、会话状态、模型/预检状态、协议版本和音频格式；监听 `olb://backend`、`olb://session`、`olb://audio`、`olb://transcript`、`olb://translation`、`olb://tts`、`olb://error` 事件展示双向字幕、TTS、音频状态、延迟和队列指标。基础设置覆盖本方/对方设备 ID、输出/虚拟麦克风路由、local/remote language、VAD/ASR/Translate 本地模型路径、TTS voice、backend base URL/token，以及默认关闭的录音/转写/翻译保存开关。

P5 启动操作会先执行预检：UI 层检查后端 URL、语言、模型路径、TTS voice 和隐私默认项；Rust `precheck_runtime_config` 会把语言、模型路径和 TTS voice 合并到运行时配置，并通过本地 Python Model Service 的 `POST /models/load` 执行模型加载/路径校验。预检失败时阻止 `start_session` / `start_audio_session`。错误 UI 会尽量从事件或错误字符串推导 type/code/module/action，并提供重新检查后端、重新枚举设备、停止复位会话等恢复操作。

`apps/desktop/src-tauri` 额外提供 `export_diagnostics` command，用于把当前状态、配置摘要、UI 运行计数、延迟/队列指标、最近事件摘要写入本地 `log_dir` 下的 `olb-diagnostic-*.json`。诊断默认不包含录音、转写正文或翻译正文，也不写入 token 明文，只记录 token 是否已配置。

MVP 不默认接入云服务，不安装虚拟音频驱动；对方音频通过用户选择的输入设备或系统已配置的虚拟输入设备采集，不通过 HTTP JSON 或 Base64 传输实时音频。普通控制 API 仍只使用 `GET` / `POST`，实时音频仍走 `WS /ws/session` 的 text/binary frame 协议。

当前 P0 骨架关闭了 Tauri bundle 打包；发布阶段再补齐图标、签名和安装包配置。
