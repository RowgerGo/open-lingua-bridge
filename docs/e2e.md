# P6 端到端联调 Runbook

本文记录 MVP P6 的可重复端到端测试流程。当前自动化覆盖 mock Python Model Service、`WS /ws/session`、`OLB1` binary frame、Rust mock realtime smoke path可用性，以及协议/模型/音频异常回归。真实设备、安装包、macOS 权限链路仍需按 `docs/release.md` 手工验证。

## 范围和约束

| 项目 | 说明 |
|---|---|
| 推理模式 | 默认使用本地 mock provider，不接入云服务。 |
| 音频传输 | 仍使用 `WS /ws/session`，text JSON 传状态/结果，binary frame 传 PCM/TTS 音频。 |
| 音频格式 | 推荐 `pcm_s16le`、16 kHz、mono。 |
| 数据保存 | 默认不保存录音、转写文本和翻译文本。 |
| 虚拟音频设备 | MVP 不安装或打包自研虚拟驱动；需要时由用户自行配置第三方设备。 |

## 测试音频样本

`python-service/src/olb/runtime/e2e.py` 提供确定性音频生成工具：

| 文件/函数 | 用途 | 确定性校验 |
|---|---|---|
| `synthetic_pcm_stream(duration_ms=250)` | 生成 mock voice/tone mono `pcm_s16le` 字节流 | SHA-256 `9254fbfa290a9ee434b4fcec62851d2db004ad628828e1acaa6211acfc78b244` |
| `python-service/tests/fixtures/synthetic_tone.wav` | 250 ms tiny WAV fixture，16 kHz，mono，16-bit | SHA-256 `447d7933e71eaa6e62c0dd00e0527354d91b762383209ca2282263af016a61dd` |

如需重新生成 fixture：

```bash
cd python-service
uv run --extra test python -c "from pathlib import Path; from olb.runtime.e2e import write_synthetic_wav; write_synthetic_wav(Path('tests/fixtures/synthetic_tone.wav'), duration_ms=250)"
```

## 一键 mock E2E

Python E2E driver 位于 `python-service/scripts/e2e_run.py`，同时提供 CLI 和 pytest entry。

```bash
cd python-service
uv run --extra test python scripts/e2e_run.py --skip-rust-binary
```

输出为 Markdown summary，示例：

```markdown
# P6 E2E summary

| Check | Result | Detail |
|---|---:|---|
| `python_ws_mock_roundtrip` | PASS | tests/fixtures/synthetic_tone.wav |
```

若本地已经存在未来的 `target/debug/olb_core` / `olb-core` 二进制，可运行：

```bash
cd python-service
uv run --extra test python scripts/e2e_run.py
```

该命令会启动本地 `uvicorn` mock service，并尝试通过现有 `olb_core` binary 触发 Rust mock realtime smoke test；当前仓库未声明该 binary 时，driver 会把 Rust binary 子步骤标为 `SKIP`，Python WebSocket mock roundtrip 仍作为自动化闭环。

## 回归测试命令

```bash
cd python-service
uv run --extra test pytest
```

覆盖内容：

| 测试文件 | 覆盖点 |
|---|---|
| `tests/test_ws_errors.py` | bad magic、oversized frame/header、truncated header、payload mismatch、protocol mismatch、unknown JSON type、missing session id、bad auth token、binary must be `audio.frame`。 |
| `tests/test_audio_anomalies.py` | binary frame audio anomaly 解码边界。 |
| `tests/test_model_failures.py` | `MODEL_FILE_MISSING`、`MODEL_LOAD_FAILED`、`LANGUAGE_CHAIN_INCOMPLETE`。 |
| `tests/test_e2e_audio.py` | PCM/WAV fixture 确定性。 |

Rust 侧：

```bash
cargo check
cargo test
```

覆盖内容：

| 位置 | 覆盖点 |
|---|---|
| `crates/olb-protocol/tests/binary_frame_errors.rs` | Rust binary frame 解码错误映射。 |
| `crates/olb-core/src/audio.rs` | `AudioError` 设备、采集、播放、重采样、播放队列过载消息。 |
| `apps/desktop/src-tauri/src/lib.rs` | `audio_error_code` 和 `realtime_error_code` UI 错误码映射。 |

前端构建：

```bash
cd apps/desktop
npm run build
```

## CI 集成建议

| 阶段 | 命令 | 说明 |
|---|---|---|
| Python | `cd python-service && uv run --extra test pytest` | 不需要真实模型或真实音频硬件。 |
| Python E2E summary | `cd python-service && uv run --extra test python scripts/e2e_run.py --skip-rust-binary` | 产出 Markdown summary，可作为 CI artifact。 |
| Rust | `cargo check && cargo test` | 不启动 Tauri bundle，不访问真实音频设备。 |
| Desktop web | `cd apps/desktop && npm run build` | 只构建 Vite/TypeScript 前端，不执行安装包签名。 |
| Release manual gates | 参考 `docs/release.md` | Windows/macOS 安装、签名、公证、真实音频链路需要人工记录。 |

## 故障排查提示

| 现象 | 常见原因 | 处理 |
|---|---|---|
| `bad auth token` / WebSocket 关闭 | `X-OLB-Auth-Token` 与 `ServiceConfig.auth_token` 不一致 | 使用默认 `dev-token` 或同步环境变量 `OLB_AUTH_TOKEN`。 |
| `PROTOCOL_VERSION_MISMATCH` | Rust/Python `protocol_version` 不一致 | 检查 `olb.schemas.protocol.PROTOCOL_VERSION` 与 `olb_protocol::PROTOCOL_VERSION`。 |
| `MODEL_FILE_MISSING` | real mode 路径为空或文件不存在 | 改用 mock 或配置本地真实模型文件路径。 |
| `LANGUAGE_CHAIN_INCOMPLETE` | ASR/翻译/TTS voice 映射不完整 | 检查语言代码和本地 voice 列表。 |
