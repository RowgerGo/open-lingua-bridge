# open-lingua-bridge 技术方案

## 1. 方案目标

本文档描述 `open-lingua-bridge` 的 MVP 技术实现方案，用于指导后续工程初始化、模块拆分、协议设计、模型服务实现、平台适配和测试验收。

MVP 目标是在 macOS 与 Windows 上跑通本地端到端实时通话翻译链路：采集本方麦克风和对方音频，将两路语音分别进行 VAD、ASR、机器翻译和 TTS，再把译文展示为字幕，并按配置输出到本机监听设备或用户已配置的虚拟音频设备。

核心技术边界：

- Tauri 负责桌面 UI、设置面板、状态展示、诊断入口和用户交互。
- Rust 负责音频采集、音频输出、实时调度、会话状态、跨进程通信和性能关键路径。
- Python 作为本地模型后端，以 sidecar 或外部本地服务运行，由 Rust/Tauri 启停和连接。
- Rust 与 Python 的 MVP 通信方式采用本地 WebSocket。
- 控制和状态消息使用 JSON；音频大负载使用 WebSocket binary frame，不使用 Base64 放入 JSON。
- MVP 默认使用本地模型服务，不默认上传音频、识别文本或翻译文本。
- MVP 不内置、不安装自研虚拟音频驱动，仅支持用户配置第三方虚拟音频设备。
- 录音、转写文本和翻译文本默认不保存，必须由用户主动开启。

## 2. 总体架构

### 2.1 架构图

```text
┌─────────────────────────────────────────────────────────────┐
│                         Tauri UI                            │
│ 主界面 / 设置界面 / 字幕面板 / 诊断面板 / 历史记录          │
└───────────────▲───────────────────────────────┬─────────────┘
                │ Tauri command/event            │
                │                                │
┌───────────────┴───────────────────────────────▼─────────────┐
│                         Rust Core                            │
│ 会话控制 / 音频采集 / 音频输出 / VAD 调度 / 协议客户端       │
│                                                             │
│ ┌───────────────┐ ┌────────────────┐ ┌───────────────────┐ │
│ │ Audio Capture │ │ Segmenter/VAD  │ │ Playback Router   │ │
│ └───────┬───────┘ └───────┬────────┘ └────────▲──────────┘ │
│         │                 │                   │            │
│         └──────────┬──────┴───────────┬───────┘            │
│                    │ WebSocket JSON + binary                │
└────────────────────▼────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                    Python Model Service                     │
│ API / Health Check / Model Manager / Pipeline Orchestrator  │
│                                                             │
│ ┌────────────┐   ┌────────────┐   ┌────────────┐           │
│ │ VAD        │   │ ASR        │   │ Translate  │           │
│ │ silero-vad │   │ faster-    │   │ NLLB       │           │
│ │            │   │ whisper    │   │            │           │
│ └────────────┘   └─────┬──────┘   └─────┬──────┘           │
│                        │                │                  │
│                        └────────┬───────┘                  │
│                                 ▼                          │
│                            ┌─────────┐                     │
│                            │ TTS     │                     │
│                            │ Piper   │                     │
│                            └─────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 分层原则

- UI 不直接访问模型，不直接处理音频实时流。
- Rust Core 是实时链路的协调者，负责低延迟音频 I/O、队列调度、状态聚合和错误恢复。
- Python Model Service 只负责模型加载、推理和模型侧队列，不负责桌面设备管理。
- 所有跨层数据都带 `session_id`、`stream_id`、`segment_id` 和 `protocol_version`。
- 本方到对方、对方到本方两条链路使用相同协议结构，通过 `direction` 区分。

## 3. 工程结构

推荐采用 monorepo 结构：

```text
open-lingua-bridge/
  apps/
    desktop/                      # Tauri 桌面应用
      src/                         # 前端 UI
      src-tauri/                   # Tauri Rust 入口

  crates/
    olb-core/                      # 会话控制、调度、状态聚合
    olb-audio/                     # 音频设备、采集、输出、重采样
    olb-protocol/                  # 协议结构、序列化、错误码
    olb-storage/                   # 配置、历史、诊断导出

  services/
    model-service/
      main.py                      # FastAPI/WebSocket 入口
      config.py
      requirements.txt
      schemas/
        protocol.py
        asr.py
        translate.py
        tts.py
      providers/
        asr/
          faster_whisper_provider.py
        vad/
          silero_vad_provider.py
        translate/
          nllb_provider.py
        tts/
          piper_provider.py
      runtime/
        model_manager.py
        session_manager.py
        pipeline_orchestrator.py
        metrics.py

  docs/
    requirements.md
    technical-solution.md
```

## 4. 运行时进程模型

### 4.1 进程组成

MVP 运行时包含两个主要进程：

1. 桌面应用进程：Tauri + Rust Core。
2. Python 模型服务进程：本地 sidecar 或用户配置的本地服务。

桌面应用负责启动、连接、健康检查和停止 Python 模型服务。若用户选择外部本地服务模式，桌面应用只连接指定地址，不负责进程生命周期。

### 4.2 启动流程

1. Tauri 启动并加载持久化配置。
2. Rust Core 枚举音频设备，加载协议版本和默认运行状态。
3. UI 展示首次配置或上次配置。
4. 用户点击开始前，Rust Core 执行预检：
   - 麦克风权限。
   - 对方音频捕获设备可用性。
   - 本机监听输出设备可用性。
   - 虚拟麦克风输出设备可用性。
   - Python 后端健康状态。
   - 模型文件存在性和语言链路完整性。
5. 预检通过后创建 `session_id`，建立或复用 WebSocket 连接。
6. Python 后端加载或热身所需模型。
7. Rust Core 启动两路音频采集和输出队列。

### 4.3 停止流程

1. UI 发起停止命令。
2. Rust Core 停止音频采集。
3. Rust Core 清空待播放 TTS 队列。
4. Rust Core 发送 `session.stop` 给 Python 后端。
5. Python 后端取消当前会话未完成任务，并释放会话级状态。
6. Rust Core 释放音频设备。
7. UI 根据配置保存或丢弃历史数据。

## 5. Rust Core 设计

### 5.1 模块职责

`olb-core`：

- 管理会话状态机。
- 维护本方到对方、对方到本方两条方向链路。
- 调度音频输入、模型请求、字幕事件和 TTS 输出。
- 聚合错误、延迟和队列状态。

`olb-audio`：

- 枚举输入设备、输出设备和虚拟音频设备。
- 采集麦克风音频和对方音频。
- 输出 TTS 音频到监听设备或虚拟麦克风。
- 处理重采样、声道转换、音量归一化和基础电平统计。

`olb-protocol`：

- 定义协议消息、错误码、状态码和版本号。
- 负责 JSON 控制消息和 binary 音频帧的编码/解码。
- 保证 Rust 与 Python 的字段命名一致。

`olb-storage`：

- 持久化用户配置。
- 保存历史记录和诊断导出。
- 执行历史删除和敏感数据开关策略。

### 5.2 会话状态机

```text
Idle
  │ start
  ▼
Prechecking
  │ pass
  ▼
StartingBackend
  │ connected + model ready
  ▼
Running
  │ pause
  ▼
Paused
  │ resume
  ▼
Running
  │ stop
  ▼
Stopping
  │ released
  ▼
Idle

Any State -- fatal/recoverable error --> Error
Error -- retry/reconnect --> Prechecking 或 Idle
```

状态说明：

- `Idle`：未启动，允许修改所有配置。
- `Prechecking`：检查设备、权限、模型和后端。
- `StartingBackend`：启动或连接 Python 后端。
- `Running`：音频采集、模型链路和输出队列运行中。
- `Paused`：保留配置和会话上下文，但停止采集和推理。
- `Stopping`：释放资源。
- `Error`：展示错误并允许重试、重新配置或停止。

## 6. 音频采集与路由

### 6.1 输入链路

MVP 支持两路输入：

- `audio_local`：本方麦克风。
- `audio_remote`：对方音频捕获设备，来源可以是系统输出音频、第三方虚拟音频设备或可枚举输入设备。

采集后的音频统一进入 Rust Core 的音频预处理管线：

```text
设备采集 -> 声道转换 -> 重采样 -> 音量统计 -> 分帧 -> VAD/分段 -> WebSocket binary frame
```

设备采集可使用平台原生能力或跨平台音频库封装，但对外接口需要统一为 PCM frame。

### 6.2 采样率与格式

设备采集和播放可使用设备默认采样率，常见为 48 kHz。进入 VAD 和 ASR 前统一转换为 16 kHz 单声道 PCM。

建议内部格式：

```text
capture_format: 平台设备原始格式
vad_format: 16 kHz mono PCM float32 或 int16
asr_format: 16 kHz mono PCM float32 或 int16
tts_format: Piper voice 输出格式或 raw PCM
playback_format: 输出设备支持格式
```

重采样边界必须明确记录在诊断信息中，包括输入采样率、输出采样率、声道数和转换失败错误。

### 6.3 输出链路

MVP 支持两类输出：

- 对方到本方方向：TTS 输出到本机监听设备，也可只显示字幕。
- 本方到对方方向：TTS 输出到用户配置的虚拟麦克风或指定输出设备。

输出队列要求：

- 同一输出设备不得叠加播放多个 TTS 片段。
- 支持按方向静音。
- 支持丢弃过期片段。
- 支持停止会话时清空队列。
- 支持延迟过高时只保留字幕，跳过 TTS 播放。

## 7. 实时分段与调度

### 7.1 分段策略

实时翻译不应将连续音频无限制发送给 ASR。Rust Core 需要按以下条件生成分段：

- VAD 检测到语音开始和结束。
- 达到最大分段时长。
- 达到最大静音等待时间。
- 会话停止或暂停时执行最终 flush。

每个分段生成唯一 `segment_id`，并保留同一 `stream_id` 和 `direction`。

### 7.2 临时结果与最终结果

`faster-whisper` 不作为原生流式 ASR 使用。MVP 采用滚动缓冲和短片段推理策略：

1. Rust Core 持续提交短音频片段。
2. Python ASR 对滚动缓冲进行推理。
3. Python 侧维护候选文本和稳定文本。
4. 稳定文本通过 `asr.partial` 发给 UI。
5. 分段结束后发送 `asr.final`。
6. 最终字幕确认后不再静默改写。

需要避免重复提交同一文本。可使用文本前缀匹配、时间戳范围和 `sequence_no` 共同去重。

### 7.3 队列调度

每个方向维护独立队列：

```text
audio_queue -> asr_queue -> translate_queue -> tts_queue -> playback_queue
```

调度规则：

- ASR 队列优先级高于 TTS 播放队列。
- 字幕结果优先于 TTS 音频输出。
- 当 TTS 队列积压导致过期时，丢弃过期 TTS，不阻塞新字幕。
- 当 Python 某阶段失败时，只标记该分段失败，不让整个会话崩溃。

## 8. Python Model Service 设计

### 8.1 服务组成

Python Model Service 使用 FastAPI/WebSocket 作为入口，包含：

- API Layer：WebSocket、健康检查、模型状态接口。
- Session Manager：维护会话、语言方向、当前 pipeline 状态。
- Model Manager：加载、卸载、热身和复用模型。
- Pipeline Orchestrator：管理 ASR、翻译、TTS 队列。
- Provider 层：封装 `faster-whisper`、`silero-vad`、`NLLB`、`Piper TTS`。
- Metrics：记录阶段耗时、队列长度和错误信息。

### 8.2 VAD Provider

MVP 首选 `silero-vad`。要求：

- 输入优先使用 16 kHz 单声道 PCM。
- 支持最小语音时长、最大分段时长、静音结束时长和 VAD 阈值配置。
- 返回语音起止时间和置信度。

VAD 可以在 Rust Core 或 Python Model Service 中执行。MVP 推荐先在 Python 侧复用 `silero-vad`，Rust 侧保留基础能量统计和音量电平展示。后续如需降低传输量，可把 VAD 前移到 Rust 或 ONNX runtime。

### 8.3 ASR Provider

MVP 首选 `faster-whisper`。要求：

- 支持模型路径、模型尺寸、设备、计算精度、线程数、beam size 和语言模式配置。
- 支持固定语言和自动语言检测。
- 返回临时结果、最终结果、置信度、起止时间戳和 `segment_id`。
- 支持模型热身。

注意事项：

- `faster-whisper` 的 `segments` 是生成器，只有迭代时才执行推理。
- 实时识别需要额外滚动缓冲和稳定文本提交策略。
- 不应把 `faster-whisper` 直接描述为完整流式 ASR。

### 8.4 Translation Provider

MVP 首选 `NLLB`。要求：

- 支持 `source_lang` 和 `target_lang`。
- 维护 UI 语言名称、ASR 语言码、NLLB/FLORES 语言码和 TTS voice 语言码映射。
- 支持短句实时翻译和有限上下文窗口。
- 返回翻译文本、处理耗时和 `segment_id`。

注意事项：

- NLLB 语言码不是普通 ISO 语言码，需要使用 NLLB/FLORES 格式。
- 长上下文可能导致质量下降，MVP 不做长文档翻译。
- 首批验收语言对需要单独定义并测试。

### 8.5 TTS Provider

MVP 首选 `Piper TTS`。要求：

- 支持 voice 文件路径、speaker、语速、音量和采样率配置。
- 校验 voice `.onnx` 文件和 `.onnx.json` 配置文件完整性。
- 校验 voice 语言与目标语言匹配。
- 展示 voice 授权或模型来源信息。
- 优先采用常驻 TTS 进程或服务复用已加载 voice。
- 支持 raw PCM 或分段 WAV 输出，并明确格式。

当目标语言没有可用 TTS voice 时，对应方向应继续支持字幕模式，并提示无法播放译音。

## 9. 协议设计

### 9.1 连接

Rust Core 作为 WebSocket client，Python Model Service 作为 WebSocket server。

推荐端点：

```text
GET /health
GET /models
GET /voices
WS  /ws/session
```

`/health` 返回协议版本、服务版本、模型服务状态和运行设备状态。

### 9.2 基础字段

所有 JSON 控制消息包含：

```json
{
  "protocol_version": "1.0",
  "type": "session.start",
  "session_id": "...",
  "stream_id": "audio_local",
  "segment_id": "...",
  "direction": "local_to_remote",
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "timestamp_ms": 0,
  "sequence_no": 1,
  "is_final": false,
  "latency_ms": 0,
  "payload": {},
  "error_code": null
}
```

### 9.3 消息类型

控制面消息：

```text
session.start
session.pause
session.resume
session.stop
config.update
status.update
error
```

数据面消息：

```text
audio.frame
asr.partial
asr.final
translate.result
tts.audio
```

### 9.4 Binary 音频帧

大音频负载使用 WebSocket binary frame。JSON metadata 先发送或通过帧头携带，binary payload 只承载 PCM 或 TTS 音频数据。

推荐 binary frame header：

```text
magic: OLB1
header_length: u32
header_json: utf8 json
payload: bytes
```

`header_json` 至少包含：

```json
{
  "protocol_version": "1.0",
  "type": "audio.frame",
  "session_id": "...",
  "stream_id": "audio_local",
  "segment_id": "...",
  "sequence_no": 1,
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "pcm_s16le",
  "timestamp_ms": 0
}
```

### 9.5 错误码

错误码按模块分组：

```text
AUDIO_DEVICE_UNAVAILABLE
AUDIO_PERMISSION_DENIED
AUDIO_CAPTURE_FAILED
AUDIO_RESAMPLE_FAILED
BACKEND_UNREACHABLE
PROTOCOL_VERSION_MISMATCH
MODEL_FILE_MISSING
MODEL_LOAD_FAILED
LANGUAGE_CHAIN_INCOMPLETE
ASR_REQUEST_FAILED
TRANSLATE_REQUEST_FAILED
TTS_REQUEST_FAILED
PLAYBACK_QUEUE_OVERLOADED
HISTORY_SAVE_FAILED
```

## 10. 配置与数据持久化

### 10.1 配置

配置保存在本地用户配置目录，建议使用 JSON 或 TOML。

配置包含：

- 本方语言和对方语言。
- 音频输入、对方音频捕获、本机监听输出、虚拟麦克风输出设备 ID。
- Python 后端地址、端口和自动启动策略。
- ASR、VAD、翻译、TTS 模型配置。
- 模型路径、缓存目录、运行设备和计算精度。
- VAD 阈值、最小语音时长、最大分段时长和静音结束时长。
- 翻译上下文窗口大小。
- TTS voice、speaker、语速、音量、输出采样率和队列过期阈值。
- 是否显示字幕。
- 是否启用本方到对方翻译。
- 是否启用对方到本方翻译。
- 是否播放 TTS。
- 是否保存录音、转写文本和翻译文本。

默认值：

- 字幕显示默认开启。
- 录音保存默认关闭。
- 转写文本保存默认关闭。
- 翻译文本保存默认关闭。
- 在线模型服务默认关闭。
- 双向 TTS 需设备预检通过后才能开启。

### 10.2 历史数据

历史记录包含：

- 会话 ID。
- 开始和结束时间。
- 语言方向。
- 每个分段的 ASR 文本、翻译文本、时间戳和方向。
- 关联录音文件路径。

关闭历史保存后，不应为新会话落盘录音、转写文本或翻译文本。删除会话历史时，需要同时删除该会话关联的录音、文本和索引记录。

## 11. 平台实现要点

### 11.1 macOS

- 需要处理麦克风权限申请和权限状态提示。
- 系统音频捕获通常依赖 BlackHole、Loopback 等第三方虚拟音频设备。
- MVP 不安装虚拟音频驱动，只提供配置说明。
- 需要处理 Apple Silicon 与 Intel Mac 的模型运行差异。
- 需要记录系统音频捕获方案、采样率和设备路由状态。

### 11.2 Windows

- 使用 WASAPI 进行音频输入输出和回放设备捕获。
- 需要处理共享模式、独占模式和采样率不匹配。
- 虚拟设备可使用 VB-CABLE 或等价方案。
- MVP 不安装虚拟音频驱动，只提供配置说明。
- 需要在设备断开或默认设备变化时刷新设备列表并提示用户。

## 12. UI 与 Tauri 集成

### 12.1 页面

主界面：

- 会话状态。
- 双向语言方向。
- 音频电平和设备状态。
- 实时字幕。
- ASR、翻译、TTS 和端到端延迟。
- 开始、暂停、恢复、停止、静音方向操作。

设置界面：

- 音频设备选择。
- 模型路径和运行设备配置。
- 语言和 voice 配置。
- VAD、ASR、翻译、TTS 参数。
- 历史保存和隐私开关。

诊断界面：

- 应用版本和协议版本。
- 操作系统版本。
- 音频设备列表。
- Python 后端连接状态。
- 模型加载状态。
- 队列长度和阶段耗时。
- 最近错误日志。

历史界面：

- 会话列表。
- 会话字幕和翻译文本。
- 删除会话历史。

### 12.2 Tauri 命令

推荐命令：

```text
list_audio_devices
get_config
save_config
precheck_session
start_session
pause_session
resume_session
stop_session
get_backend_status
list_models
list_voices
export_diagnostics
list_history
delete_history
```

### 12.3 Tauri 事件

推荐事件：

```text
session_status_changed
audio_level_updated
subtitle_updated
latency_updated
model_status_updated
audio_route_updated
error_occurred
history_updated
```

## 13. 可观测性与诊断

### 13.1 指标

需要记录：

- ASR 延迟。
- 翻译延迟。
- TTS 延迟。
- 字幕端到端延迟。
- TTS 播放端到端延迟。
- 输入音量。
- 输出队列长度。
- ASR、翻译、TTS 队列长度。
- 当前采样率、声道数和重采样状态。

### 13.2 日志

日志原则：

- 默认不记录完整音频内容。
- 默认不记录完整识别文本和翻译文本。
- 若诊断导出需要包含文本，必须由用户主动开启。
- 错误日志应包含错误码、模块、时间、会话 ID 和可读错误信息。

### 13.3 诊断导出

诊断包可包含：

- 应用版本。
- 协议版本。
- 操作系统版本。
- 音频设备列表。
- 模型配置摘要。
- 后端健康状态。
- 最近错误日志。
- 队列和延迟统计。

默认不包含录音、转写文本和翻译文本。

## 14. 隐私与安全

- 本地模型服务默认处理所有音频、文本和翻译结果。
- 在线 Provider 只作为后续扩展，不在 MVP 默认启用。
- 不允许在未获得用户确认时回退到在线服务。
- 录音、转写和翻译历史默认关闭。
- 用户开启录音或历史保存前，UI 必须展示敏感数据提示。
- 用户可以删除已有历史，删除操作应删除索引和关联文件。
- 应提示用户遵守通话录音和转写相关法律法规。

## 15. 测试方案

### 15.1 单元测试

Rust：

- 协议序列化和反序列化。
- 会话状态机。
- 队列过期和丢弃策略。
- 配置读写。
- 错误码映射。

Python：

- Provider 参数校验。
- 模型文件存在性检查。
- 语言码映射。
- 健康检查返回。
- 单阶段 ASR、翻译、TTS 调用。

### 15.2 集成测试

- Rust Core 与 Python Model Service WebSocket 连接。
- JSON 控制消息和 binary 音频帧传输。
- 单向 ASR -> 翻译 -> TTS pipeline。
- Python 后端断开和重连。
- 语言链路不完整时启动前拦截。

### 15.3 端到端测试

使用本地 WAV 或模拟音频源测试：

- 本方到对方方向。
- 对方到本方方向。
- 字幕展示。
- TTS 输出到本机监听设备。
- TTS 输出到虚拟音频设备。
- 停止会话后设备释放。

验收指标：

- 推荐硬件和推荐模型组合下，首批验收语言对的单向字幕端到端延迟 P95 低于 3 秒。
- 应用连续运行 30 分钟不崩溃。
- Python 后端断开后 UI 在 5 秒内显示错误，并允许重新连接或停止会话。
- 关闭历史保存后，新会话不产生录音、转写文本或翻译文本文件。

### 15.4 平台测试

macOS：

- 麦克风权限申请。
- 输入和输出设备枚举。
- 第三方虚拟音频设备捕获。
- 本机监听播放。
- Apple Silicon 与 Intel Mac 基础验证。

Windows：

- WASAPI 输入输出。
- 回放设备捕获。
- 共享模式和采样率不匹配。
- 虚拟音频设备输出。
- 设备断开和重新选择。

## 16. 里程碑落地

### M1：基础工程与音频原型

- 初始化 Tauri、Rust workspace 和 Python service。
- 完成音频设备枚举。
- 完成麦克风采集和本机播放。
- 完成 UI 设备选择原型。
- 完成基础配置持久化。

### M2：模型后端原型

- 完成 WebSocket 协议第一版。
- 完成健康检查和模型状态接口。
- 接入 `silero-vad`、`faster-whisper`、`NLLB`、`Piper TTS`。
- 完成模型热身和推荐模型/voice 清单。
- 完成单阶段推理测试。

### M3：单向翻译链路

- 完成对方音频捕获。
- 完成对方语音到本方语言字幕。
- 完成对方语音到本方语言 TTS 输出。
- 在 UI 展示单向字幕、延迟和错误状态。

### M4：双向翻译链路

- 完成本方语音到对方语言翻译。
- 完成本方译音输出到虚拟麦克风。
- 完成两路队列调度。
- 完成基础回声和串音规避策略。

### M5：MVP 打磨与验证

- 完成错误处理和诊断界面。
- 完成历史记录保存和删除。
- 完成隐私默认关闭策略验证。
- 完成 macOS 与 Windows 基础兼容验证。
- 完成端到端延迟测试。
- 输出使用说明和已知限制。

## 17. 风险与应对

### 17.1 音频路由风险

风险：macOS 和 Windows 的系统音频捕获、虚拟设备配置差异大。

应对：MVP 不内置驱动，只支持用户配置第三方虚拟音频设备，并在 UI 中提供预检和配置说明。

### 17.2 延迟风险

风险：本地 ASR、翻译和 TTS 同时运行可能无法在低配设备上达到 3 秒目标。

应对：提供推荐模型组合、运行设备配置、量化配置和延迟诊断；字幕优先，TTS 过期可丢弃。

### 17.3 模型覆盖风险

风险：ASR、NLLB 和 Piper 的语言覆盖不完全一致。

应对：维护语言链路映射表，启动前检查 ASR、翻译和 TTS 是否完整；不完整时允许字幕模式或阻止启动对应 TTS。

### 17.4 TTS 回环风险

风险：TTS 输出可能被本方 ASR 再次捕获，导致翻译回环。

应对：区分输入输出设备，支持方向静音和回声规避策略；必要时在播放 TTS 时短暂抑制对应输入流。

### 17.5 授权与分发风险

风险：NLLB 模型和 Piper voice 的授权、用途限制和体积影响分发。

应对：首批模型清单必须列明来源、授权、大小和用途限制；模型下载或配置前由用户确认。

## 18. 待确认事项

- 首批验收语言对。
- 推荐硬件基线，包括 CPU、内存、GPU、显存和 Apple Silicon 型号。
- 推荐 ASR 模型尺寸、NLLB 模型版本和 Piper voice 列表。
- 是否提供模型下载器，还是只支持用户手动配置本地模型路径。
- 历史记录是否支持自动清理周期。
- 首批语言对的质量验收样例和人工评分标准。
- WebSocket 协议版本兼容策略。
