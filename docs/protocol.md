# open-lingua-bridge Rust/Python 数据结构与协议文档

## 1. 文档范围

本文档定义 Rust Core 与 Python Model Service 之间的实时数据协议和核心数据结构，覆盖音频帧、ASR 识别结果、机器翻译结果、TTS 音频结果、状态更新和错误事件。

协议目标：

- 支持 Rust 与 Python 之间传输实时音频、识别结果、翻译结果和 TTS 音频。
- 大音频负载使用 WebSocket binary frame，不使用 Base64 放入 JSON。
- 控制消息和小型结果消息使用 WebSocket text JSON。
- 所有消息携带 `protocol_version`，支持后续版本演进。
- 所有链路结果通过 `session_id`、`stream_id`、`direction`、`segment_id`、`sequence_no` 串联。

## 2. 传输通道

### 2.1 连接端点

```text
WS /ws/session
```

Rust Core 作为 WebSocket client，Python Model Service 作为 WebSocket server。

### 2.2 通道类型

同一 WebSocket 连接承载两类 frame：

| WebSocket frame 类型 | 用途 | 内容 |
|---|---|---|
| text | 控制消息、小型结果、状态、错误 | UTF-8 JSON |
| binary | 音频输入帧、TTS 输出音频 | OLB binary frame |

### 2.3 方向约定

| 方向 | 发送方 | 接收方 | 说明 |
|---|---|---|---|
| uplink | Rust Core | Python Model Service | 音频帧、会话控制、配置更新 |
| downlink | Python Model Service | Rust Core | ASR、翻译、TTS、状态、错误 |

## 3. 枚举定义

### 3.1 MessageType

```text
session.start
session.pause
session.resume
session.stop
config.update
audio.frame
asr.partial
asr.final
translate.result
tts.audio
status.update
error
```

### 3.2 StreamId

```text
audio_local
audio_remote
```

`audio_local` 表示本方麦克风流。

`audio_remote` 表示对方音频捕获流。

### 3.3 Direction

```text
local_to_remote
remote_to_local
```

`local_to_remote` 表示本方语音翻译成对方语言。

`remote_to_local` 表示对方语音翻译成本方语言。

### 3.4 SampleFormat

```text
pcm_s16le
pcm_f32le
wav
```

MVP 推荐音频输入使用 `pcm_s16le`、16 kHz、mono。

### 3.5 SegmentState

```text
created
speech_started
speech_ended
asr_partial
asr_final
translated
tts_generated
played
failed
dropped
```

### 3.6 ErrorCode

```text
OK
INVALID_REQUEST
UNAUTHORIZED
PROTOCOL_VERSION_MISMATCH
BACKEND_UNREACHABLE
BACKEND_NOT_READY
AUDIO_DEVICE_UNAVAILABLE
AUDIO_PERMISSION_DENIED
AUDIO_CAPTURE_FAILED
AUDIO_RESAMPLE_FAILED
MODEL_FILE_MISSING
MODEL_LOAD_FAILED
LANGUAGE_CHAIN_INCOMPLETE
ASR_REQUEST_FAILED
TRANSLATE_REQUEST_FAILED
TTS_REQUEST_FAILED
PLAYBACK_QUEUE_OVERLOADED
SESSION_NOT_FOUND
SESSION_STATE_INVALID
INTERNAL_ERROR
```

## 4. 通用 JSON 消息结构

WebSocket text frame 使用统一 JSON envelope。

### 4.1 BaseMessage

```json
{
  "protocol_version": "1.0",
  "type": "asr.final",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 12,
  "timestamp_ms": 1780000000000,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "is_final": true,
  "latency_ms": 520,
  "payload": {},
  "error_code": null
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| protocol_version | string | 是 | 协议版本，MVP 为 `1.0` |
| type | string | 是 | 消息类型，见 `MessageType` |
| session_id | string | 是 | 会话 ID，由 Rust Core 生成 |
| stream_id | string | 否 | 音频流 ID，控制消息可为空 |
| direction | string | 否 | 翻译方向，控制消息可为空 |
| segment_id | string | 否 | 分段 ID，非分段消息可为空 |
| sequence_no | number | 是 | 同一连接内递增序号 |
| timestamp_ms | number | 是 | Unix epoch 毫秒 |
| source_lang | string | 否 | 源语言，使用系统内部语言码 |
| target_lang | string | 否 | 目标语言，使用系统内部语言码 |
| is_final | boolean | 否 | 是否最终结果 |
| latency_ms | number | 否 | 当前阶段耗时 |
| payload | object | 是 | 具体消息负载 |
| error_code | string/null | 否 | 错误码 |

### 4.2 序号规则

- `sequence_no` 在单个 WebSocket 连接内单调递增。
- Rust Core 发出的 uplink 消息和 Python 发出的 downlink 消息可以各自维护独立递增序列。
- 接收方发现重复 `sequence_no` 时可以忽略重复消息。
- 接收方发现跳号时不立即断开连接，但应记录诊断日志。

### 4.3 ID 规则

```text
session_id: ses_<唯一 ID>
segment_id: seg_<递增或唯一 ID>
request_id: req_<唯一 ID>
```

`segment_id` 由 Rust Core 的 Segment Scheduler 生成，并贯穿 ASR、翻译、TTS 和播放链路。

## 5. Binary Frame 格式

音频输入帧和 TTS 音频输出使用 WebSocket binary frame。

### 5.1 帧布局

```text
0                   4                   8
+-------------------+-------------------+-------------------+
| magic: 4 bytes    | header_len: u32le | header_json bytes |
+-------------------+-------------------+-------------------+
| payload bytes ...                                     |
+-------------------------------------------------------+
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| magic | 4 bytes | 固定为 ASCII `OLB1` |
| header_len | u32 little-endian | `header_json` 字节长度 |
| header_json | UTF-8 JSON bytes | BinaryFrameHeader |
| payload | bytes | PCM/WAV 音频数据 |

### 5.2 BinaryFrameHeader

```json
{
  "protocol_version": "1.0",
  "type": "audio.frame",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 12,
  "timestamp_ms": 1780000000000,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "pcm_s16le",
  "duration_ms": 20,
  "payload_size": 640,
  "is_final": false
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| protocol_version | string | 是 | 协议版本 |
| type | string | 是 | `audio.frame` 或 `tts.audio` |
| session_id | string | 是 | 会话 ID |
| stream_id | string | 是 | `audio_local` 或 `audio_remote` |
| direction | string | 是 | 翻译方向 |
| segment_id | string | 是 | 分段 ID |
| sequence_no | number | 是 | 递增序号 |
| timestamp_ms | number | 是 | 音频帧采集或生成时间 |
| source_lang | string | 否 | 源语言 |
| target_lang | string | 否 | 目标语言 |
| sample_rate | number | 是 | 采样率 |
| channels | number | 是 | 声道数 |
| sample_format | string | 是 | 音频格式 |
| duration_ms | number | 是 | payload 表示的音频时长 |
| payload_size | number | 是 | payload 字节数 |
| is_final | boolean | 否 | 是否该分段最后一帧 |

### 5.3 Payload 约定

音频输入 `audio.frame`：

- MVP 推荐 `pcm_s16le`。
- 推荐 16 kHz、mono。
- 单帧建议 20 ms 或 32 ms。
- 允许按 VAD/分段策略合并多个短帧发送，但不建议单帧过大。

TTS 输出 `tts.audio`：

- 可使用 `pcm_s16le` 或 `wav`。
- 若使用 `wav`，payload 是完整 WAV bytes。
- 若使用 `pcm_s16le`，Rust Core 按 header 中的采样率、声道数和格式播放。

## 6. 会话控制消息

### 6.1 session.start

发送方：Rust Core。

接收方：Python Model Service。

```json
{
  "protocol_version": "1.0",
  "type": "session.start",
  "session_id": "ses_01HZXABC",
  "stream_id": null,
  "direction": null,
  "segment_id": null,
  "sequence_no": 1,
  "timestamp_ms": 1780000000000,
  "source_lang": null,
  "target_lang": null,
  "is_final": false,
  "latency_ms": 0,
  "payload": {
    "local_lang": "cmn_Hans",
    "remote_lang": "eng_Latn",
    "directions": ["local_to_remote", "remote_to_local"],
    "enable_tts": true,
    "asr_config": {
      "provider": "faster-whisper",
      "language_mode": "fixed",
      "compute_type": "int8"
    },
    "vad_config": {
      "provider": "silero-vad",
      "sample_rate": 16000,
      "threshold": 0.5
    },
    "translate_config": {
      "provider": "nllb",
      "context_window": 3
    },
    "tts_config": {
      "provider": "piper",
      "voice_id": "en_US-lessac-medium"
    }
  },
  "error_code": null
}
```

### 6.2 session.pause

```json
{
  "protocol_version": "1.0",
  "type": "session.pause",
  "session_id": "ses_01HZXABC",
  "stream_id": null,
  "direction": null,
  "segment_id": null,
  "sequence_no": 20,
  "timestamp_ms": 1780000010000,
  "source_lang": null,
  "target_lang": null,
  "is_final": false,
  "latency_ms": 0,
  "payload": {
    "reason": "user_action"
  },
  "error_code": null
}
```

### 6.3 session.resume

```json
{
  "protocol_version": "1.0",
  "type": "session.resume",
  "session_id": "ses_01HZXABC",
  "stream_id": null,
  "direction": null,
  "segment_id": null,
  "sequence_no": 21,
  "timestamp_ms": 1780000020000,
  "source_lang": null,
  "target_lang": null,
  "is_final": false,
  "latency_ms": 0,
  "payload": {},
  "error_code": null
}
```

### 6.4 session.stop

```json
{
  "protocol_version": "1.0",
  "type": "session.stop",
  "session_id": "ses_01HZXABC",
  "stream_id": null,
  "direction": null,
  "segment_id": null,
  "sequence_no": 22,
  "timestamp_ms": 1780000030000,
  "source_lang": null,
  "target_lang": null,
  "is_final": true,
  "latency_ms": 0,
  "payload": {
    "flush": true,
    "reason": "user_action"
  },
  "error_code": null
}
```

## 7. 音频输入协议

### 7.1 audio.frame

发送方：Rust Core。

接收方：Python Model Service。

传输类型：WebSocket binary frame。

Header 示例：

```json
{
  "protocol_version": "1.0",
  "type": "audio.frame",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 101,
  "timestamp_ms": 1780000001000,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "pcm_s16le",
  "duration_ms": 20,
  "payload_size": 640,
  "is_final": false
}
```

Payload：

```text
640 bytes pcm_s16le audio payload
```

### 7.2 分段结束帧

分段最后一帧需要设置 `is_final=true`。

```json
{
  "protocol_version": "1.0",
  "type": "audio.frame",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 125,
  "timestamp_ms": 1780000002500,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "pcm_s16le",
  "duration_ms": 20,
  "payload_size": 640,
  "is_final": true
}
```

Python Model Service 收到分段结束帧后，需要对该 `segment_id` 执行最终 ASR flush。

## 8. ASR 识别结果协议

### 8.1 asr.partial

发送方：Python Model Service。

接收方：Rust Core。

传输类型：WebSocket text JSON。

```json
{
  "protocol_version": "1.0",
  "type": "asr.partial",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 201,
  "timestamp_ms": 1780000001800,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "is_final": false,
  "latency_ms": 420,
  "payload": {
    "text": "你好，很高兴",
    "language": "cmn_Hans",
    "language_probability": 0.96,
    "confidence": 0.88,
    "start_ms": 0,
    "end_ms": 1200,
    "stable": false,
    "revision": 1,
    "words": []
  },
  "error_code": null
}
```

payload 字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| text | string | 是 | 临时识别文本 |
| language | string | 是 | 识别语言 |
| language_probability | number | 否 | 语言检测概率 |
| confidence | number | 否 | 识别置信度 |
| start_ms | number | 是 | 分段内开始时间 |
| end_ms | number | 是 | 分段内结束时间 |
| stable | boolean | 是 | 是否可作为稳定文本展示 |
| revision | number | 是 | 同一分段内修订号 |
| words | array | 否 | 词级时间戳，MVP 可为空 |

### 8.2 asr.final

```json
{
  "protocol_version": "1.0",
  "type": "asr.final",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 202,
  "timestamp_ms": 1780000002600,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "is_final": true,
  "latency_ms": 560,
  "payload": {
    "text": "你好，很高兴认识你。",
    "language": "cmn_Hans",
    "language_probability": 0.97,
    "confidence": 0.91,
    "start_ms": 0,
    "end_ms": 2500,
    "revision": 2,
    "words": [
      { "text": "你好", "start_ms": 0, "end_ms": 500, "confidence": 0.94 },
      { "text": "很高兴", "start_ms": 600, "end_ms": 1200, "confidence": 0.91 },
      { "text": "认识你", "start_ms": 1300, "end_ms": 2400, "confidence": 0.89 }
    ]
  },
  "error_code": null
}
```

规则：

- `asr.partial` 可以多次发送。
- `asr.final` 对同一 `segment_id` 只能发送一次。
- Rust Core 收到 `asr.final` 后可确认原文字幕。
- `asr.final` 之后不应再发送同一 `segment_id` 的 `asr.partial`。

## 9. 翻译结果协议

### 9.1 translate.result

发送方：Python Model Service。

接收方：Rust Core。

传输类型：WebSocket text JSON。

```json
{
  "protocol_version": "1.0",
  "type": "translate.result",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 301,
  "timestamp_ms": 1780000002900,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "is_final": true,
  "latency_ms": 180,
  "payload": {
    "source_text": "你好，很高兴认识你。",
    "translated_text": "Hello, nice to meet you.",
    "source_lang": "cmn_Hans",
    "target_lang": "eng_Latn",
    "model": "nllb-200-distilled-600M",
    "context_segments": ["seg_000000"],
    "quality": {
      "score": null,
      "warnings": []
    }
  },
  "error_code": null
}
```

payload 字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| source_text | string | 是 | ASR 最终文本 |
| translated_text | string | 是 | 翻译文本 |
| source_lang | string | 是 | 源语言 |
| target_lang | string | 是 | 目标语言 |
| model | string | 否 | 翻译模型名称 |
| context_segments | array | 否 | 使用到的上下文分段 ID |
| quality | object | 否 | 质量提示，MVP 可为空 |

规则：

- `translate.result` 应基于 `asr.final` 产生。
- 同一 `segment_id` 的翻译结果 MVP 只发送一次。
- 翻译失败时发送 `error`，保留 ASR 原文字幕。

## 10. TTS 音频结果协议

### 10.1 tts.audio

发送方：Python Model Service。

接收方：Rust Core。

传输类型：WebSocket binary frame。

Header 示例：

```json
{
  "protocol_version": "1.0",
  "type": "tts.audio",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 401,
  "timestamp_ms": 1780000003300,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "sample_rate": 22050,
  "channels": 1,
  "sample_format": "pcm_s16le",
  "duration_ms": 1850,
  "payload_size": 81585,
  "is_final": true,
  "text": "Hello, nice to meet you.",
  "voice_id": "en_US-lessac-medium",
  "latency_ms": 240
}
```

Payload：

```text
pcm_s16le or wav audio bytes
```

规则：

- Rust Core 根据 `direction` 决定播放到本机监听设备或虚拟麦克风。
- 如果 TTS 队列积压，Rust Core 可以丢弃过期的 `tts.audio`。
- `tts.audio` 不影响字幕最终结果。

## 11. 状态更新协议

### 11.1 status.update

发送方：Rust Core 或 Python Model Service。

接收方：对端。

传输类型：WebSocket text JSON。

```json
{
  "protocol_version": "1.0",
  "type": "status.update",
  "session_id": "ses_01HZXABC",
  "stream_id": null,
  "direction": null,
  "segment_id": null,
  "sequence_no": 501,
  "timestamp_ms": 1780000003500,
  "source_lang": null,
  "target_lang": null,
  "is_final": false,
  "latency_ms": 0,
  "payload": {
    "session_state": "running",
    "backend_state": "ready",
    "models": {
      "vad": "loaded",
      "asr": "loaded",
      "translate": "loaded",
      "tts": "loaded"
    },
    "queues": {
      "asr_queue_size": 0,
      "translate_queue_size": 0,
      "tts_queue_size": 1
    }
  },
  "error_code": null
}
```

## 12. 错误事件协议

### 12.1 error

发送方：Rust Core 或 Python Model Service。

接收方：对端。

传输类型：WebSocket text JSON。

```json
{
  "protocol_version": "1.0",
  "type": "error",
  "session_id": "ses_01HZXABC",
  "stream_id": "audio_local",
  "direction": "local_to_remote",
  "segment_id": "seg_000001",
  "sequence_no": 601,
  "timestamp_ms": 1780000003600,
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "is_final": true,
  "latency_ms": 0,
  "payload": {
    "code": "ASR_REQUEST_FAILED",
    "message": "ASR provider failed on segment seg_000001",
    "stage": "asr",
    "recoverable": true,
    "detail": {
      "provider": "faster-whisper"
    }
  },
  "error_code": "ASR_REQUEST_FAILED"
}
```

规则：

- 分段级错误不应导致整个会话崩溃。
- 可恢复错误设置 `recoverable=true`。
- 致命错误设置 `recoverable=false`，Rust Core 应停止或进入 Error 状态。

## 13. Rust 数据结构建议

以下为 Rust 侧结构建议，字段命名使用 `snake_case`，序列化时保持与 JSON 一致。

```rust
pub struct BaseMessage<T> {
    pub protocol_version: String,
    pub r#type: MessageType,
    pub session_id: String,
    pub stream_id: Option<StreamId>,
    pub direction: Option<Direction>,
    pub segment_id: Option<String>,
    pub sequence_no: u64,
    pub timestamp_ms: u64,
    pub source_lang: Option<String>,
    pub target_lang: Option<String>,
    pub is_final: Option<bool>,
    pub latency_ms: Option<u64>,
    pub payload: T,
    pub error_code: Option<ErrorCode>,
}

pub struct BinaryFrameHeader {
    pub protocol_version: String,
    pub r#type: MessageType,
    pub session_id: String,
    pub stream_id: StreamId,
    pub direction: Direction,
    pub segment_id: String,
    pub sequence_no: u64,
    pub timestamp_ms: u64,
    pub source_lang: Option<String>,
    pub target_lang: Option<String>,
    pub sample_rate: u32,
    pub channels: u16,
    pub sample_format: SampleFormat,
    pub duration_ms: u32,
    pub payload_size: u32,
    pub is_final: Option<bool>,
}
```

## 14. Python 数据结构建议

以下为 Python 侧 Pydantic 模型建议。

```python
from typing import Any, Optional
from pydantic import BaseModel


class BaseMessage(BaseModel):
    protocol_version: str
    type: str
    session_id: str
    stream_id: Optional[str] = None
    direction: Optional[str] = None
    segment_id: Optional[str] = None
    sequence_no: int
    timestamp_ms: int
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    is_final: Optional[bool] = None
    latency_ms: Optional[int] = None
    payload: dict[str, Any]
    error_code: Optional[str] = None


class BinaryFrameHeader(BaseModel):
    protocol_version: str
    type: str
    session_id: str
    stream_id: str
    direction: str
    segment_id: str
    sequence_no: int
    timestamp_ms: int
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    sample_rate: int
    channels: int
    sample_format: str
    duration_ms: int
    payload_size: int
    is_final: Optional[bool] = None
```

## 15. Binary Frame 编解码规则

### 15.1 编码

1. 构造 `BinaryFrameHeader`。
2. 将 header 序列化为 UTF-8 JSON bytes。
3. 写入 magic `OLB1`。
4. 写入 `header_len`，格式为 little-endian `u32`。
5. 写入 header bytes。
6. 写入 payload bytes。

### 15.2 解码

1. 检查前 4 字节是否为 `OLB1`。
2. 读取后 4 字节为 `header_len`。
3. 读取指定长度 header bytes 并解析 JSON。
4. 剩余 bytes 作为 payload。
5. 校验 `payload_size` 与实际 payload 长度一致。
6. 校验 `protocol_version`、`type`、`session_id`、`segment_id`。

### 15.3 异常处理

| 场景 | 错误码 | 处理 |
|---|---|---|
| magic 不匹配 | INVALID_REQUEST | 丢弃 frame，返回 error |
| header_len 超出限制 | INVALID_REQUEST | 丢弃 frame，返回 error |
| header JSON 无法解析 | INVALID_REQUEST | 丢弃 frame，返回 error |
| payload_size 不一致 | INVALID_REQUEST | 丢弃 frame，返回 error |
| 协议版本不兼容 | PROTOCOL_VERSION_MISMATCH | 关闭会话或阻止连接 |
| session_id 不存在 | SESSION_NOT_FOUND | 返回 error |

## 16. 消息顺序与幂等规则

### 16.1 单分段顺序

正常情况下，同一 `segment_id` 的消息顺序为：

```text
audio.frame ... audio.frame(is_final=true)
  -> asr.partial ... asr.partial
  -> asr.final
  -> translate.result
  -> tts.audio
```

### 16.2 幂等规则

- `audio.frame` 可按 `sequence_no` 去重。
- `asr.partial` 以最新 `revision` 为准。
- `asr.final` 对同一 `segment_id` 只接受第一次。
- `translate.result` 对同一 `segment_id` 只接受第一次。
- `tts.audio` 若已过期，可以由 Rust Core 丢弃。

### 16.3 丢包与乱序

WebSocket 在单连接内保证消息有序到达。若应用层发现 `sequence_no` 异常：

- 记录诊断日志。
- 对临时字幕可继续处理。
- 对音频帧缺失可标记分段质量下降。
- 对最终结果缺失可在会话停止时执行 flush 或标记分段失败。

## 17. 版本兼容策略

- 当前协议版本为 `1.0`。
- 新增可选字段不提升主版本。
- 删除字段、修改字段语义、改变 binary frame 布局需要提升主版本。
- Rust Core 和 Python Model Service 建立连接时必须比较 `protocol_version`。
- 版本不兼容时返回 `PROTOCOL_VERSION_MISMATCH`，并停止实时链路。

## 18. 与普通 HTTP API 的关系

普通 HTTP API 只使用 `GET` 和 `POST`，用于健康检查、模型查询、模型加载、会话控制和单阶段测试。

实时协议使用 WebSocket：

- text JSON 传输控制消息、小型结果、状态和错误。
- binary frame 传输音频输入和 TTS 音频输出。

HTTP API 不承载实时音频大负载。
