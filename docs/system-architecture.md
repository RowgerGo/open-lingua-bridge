# open-lingua-bridge 系统架构设计

## 1. 设计目标

本文档描述 `open-lingua-bridge` MVP 的系统架构设计，重点覆盖总体架构图、模块划分、服务边界、数据流、调用链路、部署形态、关键依赖和异常处理策略。

系统架构遵循以下原则：

- 本地优先：MVP 默认使用本地模型服务，不默认上传音频、识别文本或翻译文本。
- 实时优先：音频采集、播放和调度路径由 Rust 承担，避免被模型推理阻塞。
- 边界清晰：Tauri UI、Rust Core、Python Model Service 通过明确协议交互。
- 可恢复：音频设备异常、Python 后端异常、模型请求失败均不应导致桌面应用崩溃。
- 可演进：协议从第一版开始包含 `protocol_version`，为后续 gRPC、Named Pipe、在线 Provider 等扩展预留空间。

## 2. 总体架构图

### 2.1 逻辑架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│                              用户界面                                │
│                                                                      │
│  Tauri UI                                                            │
│  ├─ 主界面：状态、字幕、延迟、音频电平                               │
│  ├─ 设置界面：设备、语言、模型、隐私开关                             │
│  ├─ 诊断界面：后端状态、模型状态、错误日志                           │
│  └─ 历史界面：会话列表、文本记录、删除                               │
└───────────────────────────────▲──────────────────────────────────────┘
                                │ Tauri command/event
                                │
┌───────────────────────────────┴──────────────────────────────────────┐
│                              Rust Core                               │
│                                                                      │
│  ├─ Session Manager：会话状态机、预检、启停控制                      │
│  ├─ Audio Capture：麦克风、系统/设备音频采集                         │
│  ├─ Audio Processing：重采样、声道转换、音量统计、分帧               │
│  ├─ Segment Scheduler：分段、队列调度、过期片段处理                  │
│  ├─ Protocol Client：WebSocket JSON + binary frame                   │
│  ├─ Playback Router：监听设备、虚拟麦克风、播放队列                  │
│  ├─ Storage：配置、历史、诊断导出                                    │
│  └─ Event Bus：向 UI 推送字幕、状态、错误和指标                      │
└───────────────────────────────▲──────────────────────────────────────┘
                                │ 本地 WebSocket
                                │ JSON 控制面 + binary 数据面
┌───────────────────────────────┴──────────────────────────────────────┐
│                         Python Model Service                         │
│                                                                      │
│  ├─ API Layer：WebSocket、Health Check、模型/voice 查询              │
│  ├─ Session Manager：会话上下文、语言方向、pipeline 状态             │
│  ├─ Model Manager：模型加载、热身、缓存、卸载                        │
│  ├─ Pipeline Orchestrator：ASR、翻译、TTS 队列                       │
│  ├─ VAD Provider：silero-vad                                         │
│  ├─ ASR Provider：faster-whisper                                     │
│  ├─ Translation Provider：NLLB                                       │
│  ├─ TTS Provider：Piper TTS                                          │
│  └─ Metrics：阶段耗时、队列长度、错误统计                            │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 运行时架构

```text
┌────────────────────────────┐
│ 桌面应用进程               │
│ Tauri + Rust Core          │
│                            │
│ - UI WebView               │
│ - Tauri command/event      │
│ - Rust audio runtime       │
│ - WebSocket client         │
│ - local storage            │
└──────────────┬─────────────┘
               │ 启动/连接/健康检查
               │
┌──────────────▼─────────────┐
│ Python 模型服务进程        │
│ sidecar 或外部本地服务     │
│                            │
│ - FastAPI/WebSocket server │
│ - model providers          │
│ - inference queues         │
│ - model cache              │
└────────────────────────────┘
```

## 3. 模块划分

### 3.1 Tauri UI

职责：

- 展示实时字幕、原文、译文、语音方向和时间戳。
- 展示运行状态、设备状态、模型状态、延迟指标和错误信息。
- 提供设备、语言、模型、TTS voice、隐私和历史保存配置入口。
- 调用 Rust command 启动、暂停、恢复和停止会话。
- 订阅 Rust event，刷新字幕、状态、指标和诊断信息。

非职责：

- 不直接采集音频。
- 不直接调用 Python 模型。
- 不处理实时队列和播放调度。

### 3.2 Rust Core

Rust Core 是桌面端实时调度核心，拆分为以下模块：

| 模块 | 主要职责 |
|---|---|
| Session Manager | 会话状态机、启动预检、暂停/恢复/停止、错误恢复 |
| Audio Device Manager | 枚举输入/输出/虚拟设备，监听设备断开和变更 |
| Audio Capture | 采集本方麦克风和对方音频捕获设备 |
| Audio Processing | 重采样、声道转换、音量归一化、电平统计、分帧 |
| Segment Scheduler | 管理音频分段、`segment_id`、队列优先级和过期策略 |
| Protocol Client | 连接 Python WebSocket，发送控制消息和 binary 音频帧 |
| Playback Router | TTS 音频输出到监听设备、虚拟麦克风或指定设备 |
| Event Bus | 向 Tauri UI 推送字幕、状态、错误、延迟和电平 |
| Storage | 配置持久化、历史记录、删除和诊断导出 |

### 3.3 Python Model Service

Python Model Service 是本地模型推理服务，拆分为以下模块：

| 模块 | 主要职责 |
|---|---|
| API Layer | WebSocket 会话、健康检查、模型列表、voice 列表 |
| Session Manager | 维护会话上下文、语言方向、当前 pipeline 状态 |
| Model Manager | 模型加载、热身、缓存、卸载和运行设备选择 |
| Pipeline Orchestrator | ASR、翻译、TTS 队列编排和阶段耗时记录 |
| VAD Provider | 封装 `silero-vad`，处理 16 kHz 单声道语音检测 |
| ASR Provider | 封装 `faster-whisper`，输出 partial/final 识别结果 |
| Translation Provider | 封装 `NLLB`，处理语言码映射和短句翻译 |
| TTS Provider | 封装 `Piper TTS`，复用 voice，输出 PCM/WAV 音频 |
| Metrics | 队列长度、阶段耗时、模型加载状态和错误统计 |

### 3.4 本地存储

本地存储由 Rust Core 统一管理：

- 用户配置：语言、设备、模型路径、后端地址、VAD/ASR/翻译/TTS 参数。
- 历史记录：用户主动开启后保存录音、转写文本和翻译文本。
- 诊断数据：默认不包含完整音频和完整文本。

## 4. 服务边界

### 4.1 UI 与 Rust Core 边界

通信方式：Tauri command/event。

UI 可以调用：

- 设备枚举。
- 配置读取和保存。
- 会话预检。
- 启动、暂停、恢复、停止会话。
- 后端状态查询。
- 模型和 voice 列表查询。
- 诊断导出。
- 历史记录查询和删除。

Rust Core 向 UI 推送：

- 会话状态。
- 音频电平。
- 字幕更新。
- 延迟指标。
- 模型状态。
- 音频路由状态。
- 错误事件。

边界约束：

- UI 不直接持有音频实时 buffer。
- UI 不直接读写模型文件。
- UI 对敏感历史数据的操作必须通过 Rust Storage 层。

### 4.2 Rust Core 与 Python Model Service 边界

通信方式：本地 WebSocket。

控制面：JSON 消息。

数据面：WebSocket binary frame。

Rust Core 负责：

- 会话生命周期。
- 音频设备和音频路由。
- 音频帧发送。
- TTS 音频播放。
- UI 状态聚合。

Python Model Service 负责：

- 模型加载和热身。
- ASR、翻译、TTS 推理。
- 模型侧队列。
- 返回结构化结果和指标。

边界约束：

- Python 不直接访问桌面音频设备。
- Rust 不直接实现 ASR、翻译、TTS 模型推理。
- 大音频负载不进入 JSON 字段。
- 所有消息必须携带 `protocol_version`。

### 4.3 应用与第三方虚拟音频设备边界

MVP 不安装、不卸载、不内置虚拟音频驱动。

系统只负责：

- 枚举用户已安装的虚拟音频设备。
- 在 UI 中提示未配置状态。
- 将 TTS 音频输出到用户选择的虚拟设备。
- 提供第三方设备配置说明。

系统不负责：

- 修改系统级音频驱动。
- 保证所有通话软件私有音频策略兼容。
- 自动完成第三方虚拟音频软件安装。

## 5. 数据流

### 5.1 本方到对方方向

```text
麦克风输入
  -> Rust Audio Capture
  -> 重采样/声道转换/音量统计
  -> 分帧和分段
  -> WebSocket binary audio.frame
  -> Python VAD/ASR
  -> Python Translation
  -> Python TTS
  -> WebSocket tts.audio
  -> Rust Playback Router
  -> 虚拟麦克风或指定输出设备
  -> 通话软件
```

同时，ASR 和翻译结果通过 Rust Event Bus 推送到 UI 字幕区域。

### 5.2 对方到本方方向

```text
系统输出音频或对方音频捕获设备
  -> Rust Audio Capture
  -> 重采样/声道转换/音量统计
  -> 分帧和分段
  -> WebSocket binary audio.frame
  -> Python VAD/ASR
  -> Python Translation
  -> Python TTS
  -> WebSocket tts.audio
  -> Rust Playback Router
  -> 本机监听输出设备
```

字幕同样通过 Rust Event Bus 推送到 UI。若用户关闭对方到本方 TTS，则链路在翻译结果处结束，只展示字幕。

### 5.3 字幕数据流

```text
Python asr.partial
  -> Rust Protocol Client
  -> Segment Scheduler 去重/合并
  -> Tauri event subtitle_updated
  -> UI 临时字幕

Python asr.final / translate.result
  -> Rust Protocol Client
  -> Segment Scheduler 确认最终分段
  -> Storage 按配置保存文本
  -> Tauri event subtitle_updated
  -> UI 最终字幕
```

临时字幕可以更新或覆盖；最终字幕确认后不应被后续结果静默改写。

### 5.4 历史数据流

```text
会话开始
  -> 读取历史保存开关
  -> 会话运行中缓存必要元数据
  -> 会话结束
  -> 若用户开启保存：写入历史索引、文本和录音
  -> 若用户关闭保存：丢弃会话敏感数据
```

默认不保存录音、转写文本和翻译文本。

## 6. 调用链路

### 6.1 启动会话调用链路

```text
用户点击开始
  -> UI 调用 start_session 或 precheck_session
  -> Rust Session Manager 执行预检
      -> Audio Device Manager 检查设备
      -> Storage 读取配置
      -> Protocol Client 调用 /health
      -> Python Model Service 返回协议版本和模型状态
      -> Model Manager 检查模型和 voice
  -> Rust Session Manager 创建 session_id
  -> Rust Protocol Client 发送 session.start
  -> Python Session Manager 创建会话上下文
  -> Python Model Manager 加载/热身模型
  -> Python 返回 status.update
  -> Rust 启动音频采集和播放队列
  -> UI 进入运行中状态
```

### 6.2 单个语音分段调用链路

```text
Audio Capture 采集 PCM frame
  -> Audio Processing 转为 16 kHz mono PCM
  -> Segment Scheduler 生成 segment_id
  -> Protocol Client 发送 audio.frame binary
  -> Python API Layer 接收帧
  -> Pipeline Orchestrator 入队
  -> VAD Provider 判断语音边界
  -> ASR Provider 输出 asr.partial/asr.final
  -> Translation Provider 输出 translate.result
  -> TTS Provider 输出 tts.audio
  -> Rust Protocol Client 接收结果
  -> Event Bus 推送字幕和延迟
  -> Playback Router 播放 TTS
```

### 6.3 暂停和恢复调用链路

暂停：

```text
用户点击暂停
  -> UI 调用 pause_session
  -> Rust 停止音频采集
  -> Rust 清空或冻结待处理队列
  -> Rust 发送 session.pause
  -> Python 暂停会话队列消费
  -> UI 显示暂停
```

恢复：

```text
用户点击恢复
  -> UI 调用 resume_session
  -> Rust 重新执行轻量设备检查
  -> Rust 发送 session.resume
  -> Python 恢复队列消费
  -> Rust 恢复音频采集
  -> UI 显示运行中
```

### 6.4 停止会话调用链路

```text
用户点击停止
  -> UI 调用 stop_session
  -> Rust 停止音频采集
  -> Rust 清空播放队列
  -> Rust 发送 session.stop
  -> Python 取消会话任务并释放会话上下文
  -> Rust 释放音频设备
  -> Storage 按用户配置保存或丢弃历史
  -> UI 回到未启动状态
```

## 7. 部署形态

### 7.1 MVP 默认形态：桌面应用 + sidecar

```text
open-lingua-bridge.app / open-lingua-bridge.exe
  ├─ Tauri UI + Rust Core
  ├─ bundled Python Model Service launcher
  ├─ user config directory
  ├─ model cache directory
  └─ optional history directory
```

特点：

- 用户启动桌面应用即可启动本地模型服务。
- Rust/Tauri 负责 sidecar 生命周期。
- WebSocket 仅监听本机地址。
- 适合 MVP 默认体验。

### 7.2 可选形态：桌面应用 + 外部本地模型服务

```text
Tauri/Rust desktop app
  -> localhost or 127.0.0.1 model-service
```

特点：

- 用户自行启动 Python 服务。
- 桌面应用只连接配置的本地地址。
- 适合开发调试、模型服务独立升级或高级用户场景。

### 7.3 非 MVP 预留形态

以下形态只预留接口，不作为 MVP 默认能力：

- Rust 与 Python 使用 gRPC。
- Rust 与 Python 使用 Unix Domain Socket 或 Windows Named Pipe。
- 在线 ASR、翻译或 TTS Provider。
- 团队账号、云端配置同步和计费系统。

## 8. 关键依赖

### 8.1 桌面与运行时

| 依赖 | 用途 | 约束 |
|---|---|---|
| Tauri | 桌面 UI、command/event、应用打包 | Python 后端作为 sidecar 或外部服务，不是 Tauri 原生能力 |
| Rust | 音频实时链路、调度、协议客户端 | 不应被模型推理阻塞 |
| Python | 模型服务和 Provider 封装 | 需要异步队列和健康检查 |
| WebSocket | Rust 与 Python 通信 | MVP 使用本地 JSON 控制面和 binary 数据面 |

### 8.2 音频与平台

| 依赖 | 用途 | 约束 |
|---|---|---|
| WASAPI | Windows 音频输入输出和回放捕获 | 需要处理共享模式、独占模式和采样率不匹配 |
| macOS 音频权限/设备 API | macOS 麦克风和设备访问 | 系统音频捕获通常依赖第三方虚拟音频设备 |
| BlackHole / Loopback | macOS 虚拟音频设备示例 | 不随 MVP 内置安装 |
| VB-CABLE | Windows 虚拟音频设备示例 | 不随 MVP 内置安装 |

### 8.3 模型与推理

| 依赖 | 用途 | 约束 |
|---|---|---|
| silero-vad | VAD | 输入优先 16 kHz 单声道 PCM |
| faster-whisper | ASR | 非原生完整流式 ASR，需要滚动缓冲和稳定文本提交策略 |
| NLLB | 机器翻译 | 需要 NLLB/FLORES 语言码映射，首批语言对需单独验收 |
| Piper TTS | TTS | voice 覆盖有限，需要校验模型文件、配置文件和授权 |

### 8.4 本地存储

| 依赖 | 用途 | 约束 |
|---|---|---|
| 配置文件 | 保存用户设置 | 不保存敏感历史内容 |
| 本地模型目录 | 保存 ASR/翻译/TTS 模型 | 需要校验存在性、完整性和授权提示 |
| 历史目录 | 保存用户主动开启的历史 | 默认关闭，删除会话需删除关联文件 |
| 诊断导出 | 排查问题 | 默认不包含完整音频和完整文本 |

## 9. 异常处理策略

### 9.1 异常分类

| 类型 | 示例 | 处理策略 |
|---|---|---|
| 可配置错误 | 虚拟设备未配置、模型路径缺失、语言链路不完整 | 启动前阻止会话，提示用户修正配置 |
| 可恢复运行时错误 | 音频设备断开、Python 后端连接中断、单个分段推理失败 | UI 展示错误，允许重连、重新选择设备或继续下一分段 |
| 性能退化 | 队列积压、TTS 延迟过高、CPU/GPU 资源不足 | 字幕优先，丢弃过期 TTS，显示延迟警告 |
| 致命错误 | 协议版本不兼容、模型服务无法启动、音频 runtime 初始化失败 | 进入 Error 状态，停止会话并释放资源 |

### 9.2 设备异常

处理策略：

- 采集设备不可用：启动前阻止会话，运行中进入可恢复错误。
- 输出设备不可用：停止对应方向 TTS 输出，字幕链路继续运行。
- 虚拟麦克风缺失：阻止本方到对方 TTS 输出，但允许字幕模式。
- 设备断开：刷新设备列表，提示用户重新选择。

### 9.3 Python 后端异常

处理策略：

- 启动失败：UI 显示后端不可用和启动日志摘要。
- 健康检查失败：阻止会话启动。
- 运行中断开：UI 在 5 秒内显示错误，Rust 停止发送新音频帧，允许重新连接或停止会话。
- 协议版本不兼容：阻止连接，提示升级或重启组件。

### 9.4 模型异常

处理策略：

- 模型文件不存在：启动前拦截。
- 模型加载失败：返回 `MODEL_LOAD_FAILED`，UI 展示模型名称和错误摘要。
- ASR 请求失败：标记当前分段失败，不中断整个会话。
- 翻译请求失败：保留 ASR 字幕，提示翻译失败。
- TTS 请求失败：保留字幕，跳过该分段播放。

### 9.5 队列和延迟异常

处理策略：

- ASR 队列积压：降低临时字幕刷新频率，必要时增加分段间隔。
- 翻译队列积压：继续展示 ASR 原文，提示翻译延迟。
- TTS 队列积压：丢弃过期 TTS，避免阻塞新字幕。
- 播放队列积压：按方向清空过期片段，保持同一输出设备不重叠播放。

### 9.6 隐私和历史异常

处理策略：

- 历史保存失败：不影响会话主链路，UI 提示保存失败。
- 用户关闭历史保存：新会话不得落盘录音、转写文本和翻译文本。
- 删除历史失败：保留错误日志，提示用户重试，不应只删除索引而遗留关联文件。

## 10. 架构约束清单

- Rust 音频采集和输出线程不得等待模型推理完成。
- Python 后端不得直接管理桌面音频设备。
- UI 不直接访问音频实时 buffer。
- 所有跨 Rust/Python 消息必须包含 `protocol_version`。
- 大音频负载必须使用 binary frame 或等价二进制通道。
- MVP 默认不启用在线 Provider。
- MVP 默认不保存录音、转写文本和翻译文本。
- MVP 不内置虚拟音频驱动。
- 最终字幕确认后不应被静默改写。
- 停止会话必须释放音频设备并清空播放队列。
