# 本地开发命令

本文记录 P0 到 P3 落地后的最小开发与验证命令。

## Python Model Service

```bash
cd python-service
uv run --extra test pytest
uv run olb-model-service --port 8765
```

服务默认监听 `127.0.0.1:8765`，控制 API 只使用 `GET` 和 `POST`，实时通道为 `WS /ws/session`。

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

桌面端提供 P1/P2/P3 控制台：显示后端状态、会话状态、音频设备、不可达错误说明，并监听 `olb://backend`、`olb://session`、`olb://audio`、`olb://transcript`、`olb://translation`、`olb://tts`、`olb://error` 事件展示字幕、TTS 与音频状态。MVP 不默认接入云服务，不安装虚拟音频驱动；对方音频通过用户选择的输入设备或系统已配置的虚拟输入设备采集，不通过 HTTP JSON 或 Base64 传输实时音频。

当前 P0 骨架关闭了 Tauri bundle 打包；发布阶段再补齐图标、签名和安装包配置。
