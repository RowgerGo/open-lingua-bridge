# MVP 发布准备说明

本文记录 Windows 与 macOS 的 MVP 构建、安装、签名/公证检查清单，以及错误码到 UI 提示和恢复动作的映射。当前仓库不启用 Tauri bundle 自动发布，不提交证书或密钥，不默认接入云服务，不默认保存录音/转写/翻译历史。

## 发布前自动化检查

| 模块 | 命令 | 期望 |
|---|---|---|
| Python service | `cd python-service && uv run --extra test pytest` | 全部通过。 |
| Python mock E2E | `cd python-service && uv run --extra test python scripts/e2e_run.py --skip-rust-binary` | Markdown summary 显示 `python_ws_mock_roundtrip` 为 PASS。 |
| Rust workspace | `cargo check && cargo test` | 全部通过。 |
| Desktop web | `cd apps/desktop && npm run build` | TypeScript 和 Vite 构建通过。 |

## Windows 构建与安装验证

| 步骤 | 命令/动作 | 验收 |
|---|---|---|
| 安装依赖 | 安装 Rust stable、Node.js LTS、Python 3.10+、uv。 | `cargo --version`、`npm --version`、`uv --version` 可用。 |
| Python service | `cd python-service && uv run olb-model-service --port 8765` | `GET http://127.0.0.1:8765/health` 返回 `status=ok`。 |
| 桌面开发启动 | `cd apps/desktop && npm run tauri dev` | UI 可启动，后端状态可显示。 |
| mock E2E | `cd python-service && uv run --extra test python scripts/e2e_run.py --skip-rust-binary` | summary PASS。 |
| 真实音频链路 | 在 UI 中选择本方输入、监听输出；如需会议软件回传，选择用户已安装的第三方虚拟音频设备。 | 可以开始/停止会话，错误可恢复，不崩溃。 |
| 记录 | 保存设备组合、系统版本、测试时间、失败截图/日志。 | 作为 P6-05 手工验证记录。 |

> 当前 Windows 自动验证覆盖 mock E2E；真实设备链路受硬件、权限和用户虚拟音频配置影响，仍需人工按本 runbook 记录。

## macOS 构建、权限与安装验证

| 步骤 | 命令/动作 | 验收 |
|---|---|---|
| 安装依赖 | 安装 Xcode Command Line Tools、Rust stable、Node.js LTS、Python 3.10+、uv。 | 基础命令可用。 |
| 麦克风权限 | 首次启动桌面端时允许麦克风权限。 | 系统设置中应用拥有麦克风权限。 |
| Python service | `cd python-service && uv run olb-model-service --port 8765` | health 正常。 |
| 桌面开发启动 | `cd apps/desktop && npm run tauri dev` | UI 可启动并连接后端。 |
| mock E2E | `cd python-service && uv run --extra test python scripts/e2e_run.py --skip-rust-binary` | summary PASS。 |
| 真实音频链路 | 使用系统输入/输出；如需会议软件回传，选择用户已安装的第三方虚拟音频设备。 | 开始/停止会话正常，错误可恢复。 |
| 记录 | 保存 macOS 版本、芯片架构、权限截图、设备组合、日志。 | 作为 P6-06 手工验证记录。 |

> 本 Windows 环境无法自动验证 macOS 签名、公证、权限弹窗和真实音频设备链路；P6-06 状态为 manual verification required。

## 代码签名和公证 checklist

| 平台 | 检查项 | 状态记录 |
|---|---|---|
| Windows | 选择 EV/OV code signing 证书，证书不入库。 | 手工记录证书主体和时间戳服务。 |
| Windows | 对安装包和主 exe 签名，校验 SmartScreen 初始提示。 | 手工记录 `signtool verify` 输出。 |
| macOS | 使用 Developer ID Application 证书签名。 | 手工记录 Team ID，不提交证书。 |
| macOS | 配置 entitlements：麦克风权限、网络访问、文件访问最小化。 | 手工记录 entitlements 文件。 |
| macOS | 执行 notarization 并 staple。 | 手工记录 notary ticket 和 `spctl` 结果。 |
| 双平台 | 不把模型文件、用户音频、转写/翻译历史默认打包或保存。 | 发布审查确认。 |

## MVP 错误码、UI 提示和恢复动作

| 错误码 | UI 提示 | 恢复动作 |
|---|---|---|
| OK | 操作成功。 | 无需处理。 |
| INVALID_REQUEST | 请求格式或协议帧无效。 | 重试操作；若持续出现，导出诊断日志并检查版本是否匹配。 |
| UNAUTHORIZED | 后端认证 token 不正确。 | 在设置中同步 Python Service token，默认开发值为 `dev-token`。 |
| PROTOCOL_VERSION_MISMATCH | 桌面端与模型服务协议版本不一致。 | 更新 Rust Core/Python Service 到同一版本后重启。 |
| BACKEND_UNREACHABLE | 无法连接 Python Model Service。 | 启动本地服务，检查 host/port、防火墙和代理设置。 |
| BACKEND_NOT_READY | 后端尚未准备完成。 | 等待模型加载完成，或切换 mock provider 验证链路。 |
| AUDIO_DEVICE_UNAVAILABLE | 选择的音频设备不可用。 | 重新枚举设备，选择系统默认输入/输出或重新插拔设备。 |
| AUDIO_PERMISSION_DENIED | 系统拒绝音频权限。 | 在 Windows/macOS 隐私设置中允许麦克风权限后重启应用。 |
| AUDIO_CAPTURE_FAILED | 音频采集失败。 | 检查设备是否被独占占用，降低采样率或切换设备。 |
| AUDIO_RESAMPLE_FAILED | 音频重采样失败。 | 确认输入采样率有效；重新选择推荐 16 kHz mono 链路。 |
| MODEL_FILE_MISSING | 模型文件不存在。 | 在设置中填写本地模型/voice 路径，或切换 mock provider。 |
| MODEL_LOAD_FAILED | 模型加载失败。 | 检查模型格式、依赖、CPU/GPU 支持和本地文件权限。 |
| LANGUAGE_CHAIN_INCOMPLETE | 当前语言链路不完整。 | 更换源/目标语言，或安装匹配的 ASR、翻译、TTS voice。 |
| ASR_REQUEST_FAILED | 语音识别失败。 | 检查 ASR 模型路径和音频输入；用 mock E2E 复现链路。 |
| TRANSLATE_REQUEST_FAILED | 翻译失败。 | 检查翻译模型路径和语言代码。 |
| TTS_REQUEST_FAILED | 语音合成或播放失败。 | 检查 TTS voice、本地输出设备和播放权限。 |
| PLAYBACK_QUEUE_OVERLOADED | 播放队列积压过多。 | 暂停会话或降低输入速率，确认输出设备可播放。 |
| SESSION_NOT_FOUND | 会话不存在或已结束。 | 重新开始会话。 |
| SESSION_STATE_INVALID | 当前会话状态不允许该操作。 | 按 UI 状态执行开始/暂停/恢复/停止，必要时重新启动应用。 |
| HISTORY_SAVE_FAILED | 诊断/历史保存失败。 | 检查导出目录权限；注意 MVP 默认不保存录音和文本历史。 |
| INTERNAL_ERROR | 内部错误。 | 导出诊断日志，重启 Python Service 和桌面端后重试。 |

## 发布记录模板

| 字段 | 内容 |
|---|---|
| 版本/commit |  |
| 平台 | Windows / macOS |
| 架构 | x64 / arm64 |
| Python 命令结果 |  |
| Rust 命令结果 |  |
| Desktop build 结果 |  |
| mock E2E summary |  |
| 真实音频设备组合 |  |
| 签名/公证结果 |  |
| 已知问题 |  |
