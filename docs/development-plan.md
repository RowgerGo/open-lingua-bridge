# open-lingua-bridge 开发计划与任务拆分

## 1. 文档目标

本文档用于指导 `open-lingua-bridge` MVP 的工程实施，明确开发阶段、任务拆分、依赖关系、优先级、交付物和验收标准。

本计划基于以下已确定边界：

- 桌面端仅面向 macOS 与 Windows。
- MVP 默认使用本地 Python Model Service，不默认使用云端模型服务。
- Tauri 负责 UI、设置、状态展示和用户交互。
- Rust Core 负责音频采集、音频输出、实时调度、会话状态和跨进程通信。
- Python Model Service 负责 VAD、ASR、机器翻译和 TTS。
- 普通控制接口只使用 `GET` 和 `POST`。
- Rust 与 Python 的实时数据面使用 `WS /ws/session`，音频和 TTS 大负载使用 WebSocket binary frame。
- MVP 不内置、不安装自研虚拟音频驱动。
- 录音、转写文本和翻译文本默认不保存。

## 2. MVP 交付目标

MVP 需要完成一条可运行、可观测、可配置的本地端到端链路：

```text
音频采集 -> 分帧/分段 -> Python 模型服务 -> ASR -> 翻译 -> TTS -> 字幕展示/音频播放
```

MVP 交付后应支持：

- 启动桌面应用并连接本地 Python Model Service。
- 选择本方麦克风、对方音频输入、本机监听输出和虚拟麦克风输出设备。
- 启动、暂停、恢复、停止实时翻译会话。
- 捕获本方麦克风音频并发送到 Python Model Service。
- 捕获对方音频或系统输出音频并发送到 Python Model Service。
- 接收 ASR 临时结果、ASR 最终结果、翻译结果和 TTS 音频结果。
- 在 UI 展示实时字幕、链路状态、错误状态和基础延迟指标。
- 按用户配置播放或路由 TTS 音频。
- 在异常场景下保持桌面应用可恢复，不因模型或设备错误崩溃。

## 3. 阶段计划

### 3.1 P0：工程骨架与基础约定

目标：建立可构建、可运行、可扩展的最小工程结构。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 | 状态 |
|---|---|---|---|---|---|---|
| P0-01 | 初始化 Tauri + Rust 工程结构 | Tauri/Rust | P0 | 无 | 可启动桌面应用骨架 | 已完成 |
| P0-02 | 初始化 Python Model Service 工程结构 | Python | P0 | 无 | 可启动本地服务骨架 | 已完成 |
| P0-03 | 定义统一配置目录、日志目录和运行时目录 | Rust/Python | P0 | P0-01, P0-02 | 配置与日志路径约定 | 已完成 |
| P0-04 | 建立错误码、协议版本、基础类型常量 | Rust/Python | P0 | P0-01, P0-02 | 两端一致的基础枚举 | 已完成 |
| P0-05 | 建立本地开发启动脚本 | 工程化 | P0 | P0-01, P0-02 | 一键启动 UI、Rust、Python 的开发命令 | 已完成 |

验收标准：

- 桌面应用可以启动到空白或占位主界面。
- Python Model Service 可以本地启动并返回健康检查结果。
- Rust 与 Python 均能读取基础配置。
- 开发者可以通过文档命令启动最小开发环境。

### 3.2 P1：控制面接口与服务生命周期

目标：跑通 UI、Rust Core、Python Model Service 的控制面调用。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 | 状态 |
|---|---|---|---|---|---|---|
| P1-01 | 实现 Rust Core 会话状态机 | Rust | P0 | P0-04 | idle/starting/running/paused/stopped/error 状态 | 已完成 |
| P1-02 | 实现 Python 健康检查接口 | Python | P0 | P0-02 | `GET /health` | 已完成 |
| P1-03 | 实现 Python 模型查询接口 | Python | P0 | P0-02 | `GET /models`、`GET /voices` | 已完成 |
| P1-04 | 实现 Python 模型加载接口 | Python | P0 | P1-03 | `POST /models/load` | 已完成 |
| P1-05 | 实现 Rust 到 Python 的 HTTP client | Rust | P0 | P1-02 | token、协议版本、错误响应处理 | 已完成 |
| P1-06 | 实现 Tauri commands | Tauri/Rust | P0 | P1-01, P1-05 | start/pause/resume/stop/get_status/update_config | 已完成 |
| P1-07 | 实现 Python sidecar 启停或外部服务连接 | Rust/Python | P1 | P1-02, P1-05 | 后端连接管理 | 已完成（外部服务连接模式） |

验收标准：

- UI 可以触发会话开始、暂停、恢复和停止。
- Rust Core 可以检查 Python 服务健康状态。
- Python 服务可以返回模型和 voice 可用性。
- token 和协议版本校验失败时返回明确错误。
- Python 服务不可达时 UI 展示可理解错误。

### 3.3 P2：实时协议与链路模拟

目标：在未接入真实模型前，先跑通 Rust/Python WebSocket JSON + binary 协议。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 | 状态 |
|---|---|---|---|---|---|---|
| P2-01 | 实现 WebSocket server `WS /ws/session` | Python | P0 | P1-02 | Python 实时协议入口 | 已完成 |
| P2-02 | 实现 Rust WebSocket client | Rust | P0 | P1-05 | 连接、重连、关闭、错误处理 | 已完成（mock smoke test client） |
| P2-03 | 实现 `BaseMessage` 编解码 | Rust/Python | P0 | P0-04 | text JSON 消息互通 | 已完成 |
| P2-04 | 实现 `BinaryFrameHeader` 编解码 | Rust/Python | P0 | P2-01, P2-02 | OLB1 binary frame 互通 | 已完成 |
| P2-05 | 实现协议模拟 pipeline | Python | P0 | P2-03, P2-04 | 模拟 ASR/翻译/TTS 返回 | 已完成 |
| P2-06 | 实现 Rust 事件总线到 UI | Rust/Tauri | P0 | P2-03 | 字幕、状态、错误事件推送 | 已完成 |
| P2-07 | 添加协议级测试样例 | Rust/Python | P1 | P2-03, P2-04 | 编解码和错误场景测试 | 已完成 |

验收标准：

- Rust 可以向 Python 发送 `session.start` 和 `audio.frame`。
- Python 可以返回 `asr.partial`、`asr.final`、`translate.result`、`tts.audio`、`status.update` 和 `error`。
- WebSocket binary frame 的 `magic`、`header_len`、`payload_size` 校验生效。
- UI 可以展示模拟字幕和状态更新。
- 不使用 Base64 在 JSON 中传输音频大负载。

### 3.4 P3：音频采集、处理与播放

目标：完成真实音频设备链路，让 Rust Core 可以采集、分帧、输出音频。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 | 状态 |
|---|---|---|---|---|---|---|
| P3-01 | 枚举输入/输出音频设备 | Rust | P0 | P0-01 | 设备列表与默认设备识别 | 已完成 |
| P3-02 | 实现麦克风音频采集 | Rust | P0 | P3-01 | `audio_local` PCM 帧 | 已完成 |
| P3-03 | 实现系统输出或指定设备音频采集 | Rust | P0 | P3-01 | `audio_remote` PCM 帧 | 已完成（选定输入设备/系统配置的虚拟输入模式） |
| P3-04 | 实现重采样与声道转换 | Rust | P0 | P3-02, P3-03 | 16 kHz mono `pcm_s16le` 输入 | 已完成 |
| P3-05 | 实现音频分帧和 `sequence_no` 管理 | Rust | P0 | P3-04 | 稳定发送 `audio.frame` | 已完成 |
| P3-06 | 实现分段调度和 `segment_id` 管理 | Rust | P0 | P3-05 | 分段生命周期 | 已完成 |
| P3-07 | 实现 TTS 音频播放队列 | Rust | P0 | P2-04 | 播放 `tts.audio` payload | 已完成 |
| P3-08 | 实现输出设备和虚拟麦克风路由 | Rust | P1 | P3-07 | 可选目标设备播放 | 已完成（不安装自研虚拟音频驱动） |

验收标准：

- UI 可以展示可用音频设备。
- 本方麦克风音频可被采集并发送给 Python。
- 对方音频或系统输出音频可被采集并发送给 Python。
- Rust 发送给 Python 的音频满足协议中的采样率、声道数和格式约定。
- Python 返回的 TTS 音频可以被 Rust 播放到指定设备。
- 设备不可用、权限不足、播放队列积压时返回明确错误或状态。

### 3.5 P4：Python 模型 Pipeline

目标：接入本地 VAD、ASR、机器翻译和 TTS，实现真实模型推理链路。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 |
|---|---|---|---|---|---|
| P4-01 | 实现模型配置加载与路径校验 | Python | P0 | P1-04 | 模型可用性检查 |
| P4-02 | 接入 silero-vad | Python | P0 | P4-01 | 语音活动检测能力 |
| P4-03 | 接入 faster-whisper | Python | P0 | P4-01, P4-02 | ASR 临时/最终结果 |
| P4-04 | 实现滚动缓冲和最终 flush | Python | P0 | P4-03 | 稳定分段识别 |
| P4-05 | 接入 NLLB 翻译模型 | Python | P0 | P4-01 | `translate.result` |
| P4-06 | 实现语言码映射和链路校验 | Python | P0 | P4-05 | ASR/翻译/TTS 语言兼容检查 |
| P4-07 | 接入 Piper TTS | Python | P0 | P4-01, P4-06 | `tts.audio` binary frame |
| P4-08 | 实现 pipeline 队列和过期任务丢弃 | Python | P1 | P4-03, P4-05, P4-07 | 低延迟调度策略 |

验收标准：

- Python 服务可以加载并检查 VAD、ASR、翻译和 TTS 模型。
- 输入 `audio.frame` 后可以产生 ASR 结果、翻译结果和 TTS 音频。
- 对同一 `segment_id`，`asr.final` 和 `translate.result` 只发送一次。
- 模型文件缺失、语言链路不完整、TTS voice 不可用时返回明确错误。
- 模型处理慢于实时输入时能够限制队列并丢弃过期任务。

### 3.6 P5：桌面 UI 与用户体验

目标：让用户可以完成基础配置、启动链路、观察字幕和处理错误。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 |
|---|---|---|---|---|---|
| P5-01 | 实现主界面状态区 | Tauri UI | P0 | P1-06 | 会话状态、后端状态、模型状态 |
| P5-02 | 实现实时字幕面板 | Tauri UI | P0 | P2-06 | 原文、译文、方向、时间戳 |
| P5-03 | 实现基础设置界面 | Tauri UI | P0 | P3-01, P1-03 | 设备、语言、模型、TTS voice |
| P5-04 | 实现启动前预检提示 | Tauri UI/Rust | P0 | P1-06, P4-06 | 缺失配置阻止启动 |
| P5-05 | 实现延迟与队列指标展示 | Tauri UI/Rust/Python | P1 | P4-08 | ASR/翻译/TTS/端到端延迟 |
| P5-06 | 实现错误提示和恢复操作 | Tauri UI | P0 | P1-06 | 后端不可达、设备不可用、模型失败提示 |
| P5-07 | 实现诊断信息导出 | Tauri UI/Rust/Python | P1 | P5-05 | 日志和运行状态导出 |

验收标准：

- 用户可以在 UI 中配置设备、语言和模型路径。
- 用户可以启动、暂停、恢复、停止会话。
- UI 可以展示两路字幕和链路状态。
- 错误提示包含错误类型、涉及模块和建议操作。
- 默认不保存录音、转写文本和翻译文本。

### 3.7 P6：端到端联调、测试与发布准备

目标：验证 MVP 在 macOS 和 Windows 上可运行、可恢复、可诊断。

主要任务：

| 编号 | 任务 | 负责人模块 | 优先级 | 依赖 | 交付物 |
|---|---|---|---|---|---|
| P6-01 | 建立端到端联调脚本和测试音频样本 | 测试/工程化 | P0 | P4-07 | 可重复 E2E 测试流程 |
| P6-02 | 覆盖协议兼容和错误场景测试 | Rust/Python | P0 | P2-07 | 协议错误测试 |
| P6-03 | 覆盖设备异常和权限异常测试 | Rust/UI | P0 | P3-08, P5-06 | 平台异常测试 |
| P6-04 | 覆盖模型缺失、加载失败、语言链路不完整测试 | Python/UI | P0 | P4-06, P5-06 | 模型异常测试 |
| P6-05 | 做 Windows 端安装和音频链路验证 | 发布 | P0 | P6-01 | Windows MVP 验证记录 |
| P6-06 | 做 macOS 端安装、权限和音频链路验证 | 发布 | P0 | P6-01 | macOS MVP 验证记录 |
| P6-07 | 整理 MVP 使用说明和故障排查文档 | 文档 | P1 | P6-05, P6-06 | 用户使用文档 |

验收标准：

- Windows 和 macOS 均可启动应用并连接 Python Model Service。
- 两路音频至少在推荐设备组合下完成端到端链路。
- 常见错误可被 UI 捕获并展示，不导致应用崩溃。
- 开发者可以通过测试音频复现 ASR、翻译、TTS 链路。
- 发布包或开发包包含必要的模型路径配置说明。

## 4. 任务依赖路径

MVP 的关键路径如下：

```text
工程骨架
  -> 控制面接口
  -> WebSocket 协议互通
  -> 音频采集/播放
  -> Python 模型 pipeline
  -> UI 集成
  -> 端到端测试
```

可以并行推进的任务：

- Tauri UI 骨架、Rust Core 骨架、Python Service 骨架可以并行启动。
- HTTP 控制面和 WebSocket 协议可以在模型接入前先用 mock pipeline 联调。
- 音频设备枚举和 Python 模型管理可以并行开发。
- UI 字幕面板可以先接入模拟事件，再接入真实模型结果。
- 协议测试和模型加载测试可以独立编写。

不能提前合并的依赖：

- 真实音频链路依赖 WebSocket binary frame 编解码完成。
- 真实 TTS 播放依赖 Rust 播放队列和 Python TTS 输出协议完成。
- 启动前预检依赖设备枚举、模型查询和语言链路校验完成。
- 端到端发布验证依赖 Windows/macOS 的真实设备测试完成。

## 5. 里程碑

| 里程碑 | 范围 | 完成标志 |
|---|---|---|
| M1：工程可运行 | P0 | UI 和 Python 服务均可本地启动 |
| M2：控制面可用 | P1 | UI 可以控制会话，Rust 可以查询 Python 状态 |
| M3：协议链路可用 | P2 | mock 音频、字幕、翻译和 TTS 协议闭环通过 |
| M4：音频链路可用 | P3 | Rust 可采集并播放真实音频 |
| M5：模型链路可用 | P4 | Python 可产生真实 ASR、翻译和 TTS 结果 |
| M6：产品闭环可用 | P5 | 用户可以通过 UI 完成配置、启动和观察结果 |
| M7：MVP 可验收 | P6 | Windows/macOS 推荐链路端到端通过 |

## 6. 模块级任务清单

### 6.1 Tauri UI

- 主界面：会话状态、后端状态、模型状态、音频电平。
- 字幕面板：本方原文、本方译文、对方原文、对方译文。
- 设置界面：音频设备、语言方向、模型路径、TTS voice、后端地址。
- 诊断界面：错误列表、日志级别、导出入口。
- Tauri commands：开始、暂停、恢复、停止、获取状态、更新配置。
- Event listener：字幕、状态、错误、指标更新。

### 6.2 Rust Core

- Session Manager：状态机、预检、启动停止、错误恢复。
- Audio Capture：麦克风和对方音频采集。
- Audio Processing：重采样、声道转换、分帧、音量统计。
- Segment Scheduler：分段 ID、队列、过期分段、最终 flush。
- Protocol Client：HTTP client、WebSocket client、JSON/binary 编解码。
- Playback Router：监听输出、虚拟麦克风输出、队列积压处理。
- Event Bus：向 UI 推送字幕、状态、错误、指标。
- Config/Storage：默认配置、用户配置、诊断日志；默认不保存音频和文本内容。

### 6.3 Python Model Service

- API Layer：健康检查、模型查询、模型加载、voice 查询、单阶段测试。
- WebSocket Session：`WS /ws/session`、text JSON、binary frame。
- Model Manager：模型路径校验、加载、热身、释放。
- VAD Provider：silero-vad 输入适配。
- ASR Provider：faster-whisper、滚动缓冲、临时结果、最终 flush。
- Translation Provider：NLLB、语言码映射、结果校验。
- TTS Provider：Piper、voice 校验、音频输出。
- Pipeline Orchestrator：队列、超时、取消、过期任务丢弃。
- Error Mapper：模型异常映射为统一错误码。

### 6.4 测试与工程化

- Rust 单元测试：协议编解码、状态机、分段调度。
- Python 单元测试：模型配置、协议编解码、语言链路校验。
- 集成测试：HTTP 控制面、WebSocket text/binary、mock pipeline。
- 端到端测试：测试音频输入到字幕和 TTS 输出。
- 平台测试：Windows 设备、macOS 权限、虚拟音频设备配置。
- 发布检查：启动脚本、配置样例、故障排查文档。

## 7. 验收标准

### 7.1 功能验收

- 可以在 Windows 和 macOS 启动桌面应用。
- 可以启动或连接本地 Python Model Service。
- 可以配置音频输入、输出、语言方向和模型路径。
- 可以启动实时翻译会话。
- 可以看到 ASR 临时字幕、ASR 最终字幕和翻译字幕。
- 可以按配置播放 TTS 音频。
- 可以暂停、恢复和停止会话。
- 设备、后端、模型和协议错误可被 UI 展示。

### 7.2 协议验收

- 普通接口只使用 `GET` 和 `POST`。
- `GET` 请求只使用 query params。
- `POST` 请求只使用 JSON body。
- 实时音频输入和 TTS 输出只通过 WebSocket binary frame 传输。
- WebSocket text JSON 只承载控制消息、小型结果、状态和错误。
- 所有 Rust/Python 协议消息包含 `protocol_version`。
- `asr.final`、`translate.result` 对同一 `segment_id` 在 MVP 中只接受一次。

### 7.3 性能与稳定性验收

- 音频采集和播放路径不被模型推理阻塞。
- 模型处理变慢时队列不会无限增长。
- Python Model Service 崩溃或不可达时 Rust Core 可以进入可恢复错误状态。
- 音频设备断开时 UI 能提示并允许重新选择设备。
- 默认不保存录音、转写文本和翻译文本。

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| faster-whisper 不提供完整原生流式 ASR | 临时字幕稳定性不足 | 使用滚动缓冲、稳定文本提交和最终 flush |
| Windows/macOS 音频设备行为差异大 | 设备链路不稳定 | 优先支持推荐设备组合，增加设备诊断信息 |
| MVP 不内置虚拟音频驱动 | 用户配置门槛较高 | 在文档中说明第三方虚拟设备配置方式 |
| 本地模型体积大、加载慢 | 首次体验差 | 提供模型状态、加载进度和推荐模型组合 |
| NLLB 与 ASR/TTS 语言码不一致 | 语言链路不可用 | 建立语言码映射表和启动前预检 |
| Piper voice 覆盖有限 | 某些目标语言无法播报 | voice 查询中明确可用性，不可用时降级为字幕 |
| 实时链路延迟过高 | 通话体验下降 | 分阶段记录 ASR、翻译、TTS 和端到端延迟 |

## 9. 非 MVP 延后项

以下能力不进入 MVP 主线：

- 自研或随应用安装虚拟音频驱动。
- 云端账号、计费、团队管理。
- 术语库、记忆库、行业词典。
- 多人会议说话人分离。
- 视频翻译、唇形同步。
- 浏览器插件、移动端、Web 端。
- 录音和转写历史默认保存。
- 对所有通话软件做深度集成。

## 10. 推荐实施顺序

推荐按以下顺序推进：

1. 先完成 P0 和 P1，保证工程可运行、控制面可调用。
2. 再完成 P2，用 mock pipeline 验证协议，不等待真实模型接入。
3. 并行推进 P3 音频链路和 P4 模型 pipeline。
4. 在 P3/P4 初步可用后推进 P5 UI 完整集成。
5. 最后用 P6 对 Windows/macOS 做端到端验证和发布准备。

每个阶段都应保持可运行状态，避免长期只实现单侧模块而无法联调。
