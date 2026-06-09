# 本地开发命令

本文记录 P0 到 P1-P2 落地后的最小开发与验证命令。

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
- `crates/olb-core`：配置、会话状态机、Python Model Service HTTP client 骨架。
- `apps/desktop/src-tauri`：Tauri v2 桌面应用 Rust 入口与 `get_status`、`get_config`、`update_config`、`start_session`、`pause_session`、`resume_session`、`stop_session` commands。

Python 测试包含 `WS /ws/session` mock roundtrip：ASR/翻译结果通过 WebSocket text JSON 返回，`tts.audio` 通过 `OLB1` binary frame 返回。

## Tauri Desktop

```bash
cd apps/desktop
npm install
npm run tauri dev
```

桌面端当前是占位界面，用于验证 Tauri/Rust command 与后续控制面接入。MVP 不默认接入云服务，不安装虚拟音频驱动，不通过 HTTP JSON 或 Base64 传输实时音频。

当前 P0 骨架关闭了 Tauri bundle 打包；发布阶段再补齐图标、签名和安装包配置。
