# open-lingua-bridge 接口/API 文档

## 1. 文档范围

本文档定义前端、Rust Core、Python Model Service 之间的控制面和查询类接口。

接口分为两类：

- 前端 UI -> Rust Core：通过 Tauri command 调用。文档中按 API 形式描述，便于统一参数和返回结构。
- Rust Core -> Python Model Service：通过本地 HTTP API 调用，MVP 只使用 `GET` 和 `POST`。

明确约束：普通接口只使用 `GET` 和 `POST`；Rust Core 与 Python Model Service 之间的实时音频数据面使用 WebSocket binary。实时音频帧和 TTS 音频数据不在 GET/POST JSON 接口中传输，也不使用 Base64 放入 JSON。本文档主要描述会话控制、配置、查询、健康检查、模型检查、单阶段测试和诊断接口，并在第 6 章单独说明实时数据面。

## 2. 通用约定

### 2.1 请求方法

- `GET`：只使用 query params 传参，例如 `?a=1&b=2`。
- `POST`：只使用 JSON body 传参。
- 不使用 `PUT`、`PATCH`、`DELETE`。

### 2.2 通用请求头

Rust Core -> Python Model Service：

```text
Content-Type: application/json
X-OLB-Protocol-Version: 1.0
X-OLB-Client: rust-core
X-OLB-Auth-Token: <local_token>
```

前端 UI -> Rust Core 为 Tauri 本地调用，不需要 HTTP 请求头。若文档示例中出现前端接口，`headers` 字段仅表示逻辑鉴权上下文，不表示真实浏览器 HTTP 请求。

### 2.3 通用响应结构

所有接口统一返回：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {},
  "request_id": "req_01HZX...",
  "protocol_version": "1.0"
}
```

错误响应：

```json
{
  "success": false,
  "code": "BACKEND_UNREACHABLE",
  "message": "Python model service is not reachable",
  "data": null,
  "request_id": "req_01HZX...",
  "protocol_version": "1.0"
}
```

### 2.4 鉴权方式

MVP 只允许本机通信，不提供远程公网 API。

前端 UI -> Rust Core：

- 通过 Tauri command/event 本地调用。
- 不暴露浏览器可直接访问的远程 HTTP 接口。
- 调用权限由 Tauri 应用配置和 Rust command 白名单控制。

Rust Core -> Python Model Service：

- Python 服务默认只监听 `127.0.0.1`。
- Rust Core 启动 Python sidecar 时生成一次性本地 token。
- Rust Core 请求时通过 `X-OLB-Auth-Token` 传递 token。
- Python 服务校验 token 和 `X-OLB-Protocol-Version`。
- 外部本地服务模式下，用户需要在配置中填写本地服务地址和 token。

### 2.5 错误码

| 错误码 | 含义 | 典型处理 |
|---|---|---|
| OK | 请求成功 | 无 |
| INVALID_REQUEST | 请求参数缺失或格式错误 | UI 提示用户修正配置 |
| UNAUTHORIZED | token 缺失或无效 | 重新连接后端或重新启动 sidecar |
| PROTOCOL_VERSION_MISMATCH | 协议版本不兼容 | 提示升级或重启组件 |
| BACKEND_UNREACHABLE | Python 后端不可连接 | UI 提示启动或重新连接 |
| BACKEND_NOT_READY | Python 后端启动中或模型未就绪 | 等待或重试 |
| AUDIO_DEVICE_UNAVAILABLE | 音频设备不可用 | 重新选择设备 |
| AUDIO_PERMISSION_DENIED | 麦克风权限未授权 | 引导用户授权 |
| MODEL_FILE_MISSING | 模型文件不存在 | 修正模型路径 |
| MODEL_LOAD_FAILED | 模型加载失败 | 展示模型错误摘要 |
| LANGUAGE_CHAIN_INCOMPLETE | ASR/翻译/TTS 语言链路不完整 | 阻止启动或切换字幕模式 |
| ASR_REQUEST_FAILED | ASR 请求失败 | 标记当前分段失败 |
| TRANSLATE_REQUEST_FAILED | 翻译请求失败 | 保留 ASR 原文并提示 |
| TTS_REQUEST_FAILED | TTS 请求失败 | 保留字幕并跳过播放 |
| SESSION_NOT_FOUND | 会话不存在 | UI 刷新状态 |
| SESSION_STATE_INVALID | 会话状态不允许当前操作 | UI 禁用对应操作 |
| HISTORY_SAVE_FAILED | 历史保存失败 | 不影响主链路，提示保存失败 |
| INTERNAL_ERROR | 内部错误 | 记录诊断日志 |

## 3. 前端 UI -> Rust Core 接口

以下接口以 Tauri command 表示，接口地址使用逻辑路径表示，不是真实 HTTP URL。

### 3.1 获取应用状态

接口地址：`/core/status`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| include_diagnostics | boolean | 否 | 是否返回诊断摘要 |

示例请求：

```text
GET /core/status?include_diagnostics=true
```

响应参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| session_state | string | `idle`、`prechecking`、`running`、`paused`、`error` |
| backend_status | string | Python 后端状态 |
| protocol_version | string | 协议版本 |
| current_session_id | string/null | 当前会话 ID |
| diagnostics | object/null | 诊断摘要 |

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "session_state": "idle",
    "backend_status": "ready",
    "protocol_version": "1.0",
    "current_session_id": null,
    "diagnostics": {
      "asr_queue_size": 0,
      "tts_queue_size": 0,
      "last_error": null
    }
  },
  "request_id": "req_status_001",
  "protocol_version": "1.0"
}
```

### 3.2 获取配置

接口地址：`/core/config`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| profile | string | 否 | 配置 profile，默认 `default` |

示例请求：

```text
GET /core/config?profile=default
```

响应参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| profile | string | 配置 profile |
| languages | object | 本方语言和对方语言 |
| devices | object | 音频设备配置 |
| backend | object | Python 后端配置 |
| models | object | 模型配置 |
| privacy | object | 历史保存和诊断隐私配置 |

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "profile": "default",
    "languages": {
      "local_lang": "cmn_Hans",
      "remote_lang": "eng_Latn"
    },
    "devices": {
      "microphone_id": "mic_default",
      "remote_capture_device_id": "loopback_default",
      "monitor_output_device_id": "speaker_default",
      "virtual_microphone_device_id": "vb_cable_input"
    },
    "backend": {
      "mode": "sidecar",
      "base_url": "http://127.0.0.1:8765"
    },
    "models": {
      "asr_provider": "faster-whisper",
      "vad_provider": "silero-vad",
      "translate_provider": "nllb",
      "tts_provider": "piper"
    },
    "privacy": {
      "save_recording": false,
      "save_transcript": false,
      "save_translation": false
    }
  },
  "request_id": "req_config_001",
  "protocol_version": "1.0"
}
```

### 3.3 保存配置

接口地址：`/core/config/save`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| profile | string | 是 | 配置 profile |
| languages | object | 是 | 语言配置 |
| devices | object | 是 | 设备配置 |
| backend | object | 是 | 后端配置 |
| models | object | 是 | 模型配置 |
| privacy | object | 是 | 隐私配置 |

示例请求：

```json
{
  "profile": "default",
  "languages": {
    "local_lang": "cmn_Hans",
    "remote_lang": "eng_Latn"
  },
  "devices": {
    "microphone_id": "mic_default",
    "remote_capture_device_id": "loopback_default",
    "monitor_output_device_id": "speaker_default",
    "virtual_microphone_device_id": "vb_cable_input"
  },
  "backend": {
    "mode": "sidecar",
    "base_url": "http://127.0.0.1:8765"
  },
  "models": {
    "asr_model_path": "D:/models/faster-whisper-small",
    "nllb_model_path": "D:/models/nllb-200-distilled-600M",
    "piper_voice_path": "D:/models/piper/en_US-lessac-medium.onnx"
  },
  "privacy": {
    "save_recording": false,
    "save_transcript": false,
    "save_translation": false
  }
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Config saved",
  "data": {
    "profile": "default",
    "saved_at": "2026-06-09T10:00:00+08:00"
  },
  "request_id": "req_config_save_001",
  "protocol_version": "1.0"
}
```

### 3.4 枚举音频设备

接口地址：`/core/audio/devices`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| kind | string | 否 | `input`、`output`、`all`，默认 `all` |
| refresh | boolean | 否 | 是否强制刷新 |

示例请求：

```text
GET /core/audio/devices?kind=all&refresh=true
```

响应参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| devices | array | 设备列表 |
| default_input_id | string/null | 默认输入设备 ID |
| default_output_id | string/null | 默认输出设备 ID |

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "default_input_id": "mic_default",
    "default_output_id": "speaker_default",
    "devices": [
      {
        "id": "mic_default",
        "name": "Default Microphone",
        "kind": "input",
        "sample_rates": [16000, 48000],
        "channels": [1, 2],
        "is_default": true,
        "is_virtual": false
      }
    ]
  },
  "request_id": "req_devices_001",
  "protocol_version": "1.0"
}
```

### 3.5 会话预检

接口地址：`/core/session/precheck`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| profile | string | 是 | 配置 profile |
| check_backend | boolean | 否 | 是否检查 Python 后端 |
| check_models | boolean | 否 | 是否检查模型 |
| check_devices | boolean | 否 | 是否检查设备 |

示例请求：

```json
{
  "profile": "default",
  "check_backend": true,
  "check_models": true,
  "check_devices": true
}
```

响应参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| passed | boolean | 是否通过 |
| checks | array | 检查项结果 |

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Precheck completed",
  "data": {
    "passed": true,
    "checks": [
      { "name": "microphone", "passed": true, "code": "OK", "message": "" },
      { "name": "backend", "passed": true, "code": "OK", "message": "" },
      { "name": "language_chain", "passed": true, "code": "OK", "message": "" }
    ]
  },
  "request_id": "req_precheck_001",
  "protocol_version": "1.0"
}
```

### 3.6 启动会话

接口地址：`/core/session/start`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| profile | string | 是 | 配置 profile |
| local_lang | string | 是 | 本方语言 |
| remote_lang | string | 是 | 对方语言 |
| enable_local_to_remote | boolean | 是 | 是否启用本方到对方方向 |
| enable_remote_to_local | boolean | 是 | 是否启用对方到本方方向 |
| enable_tts | boolean | 是 | 是否启用 TTS |

示例请求：

```json
{
  "profile": "default",
  "local_lang": "cmn_Hans",
  "remote_lang": "eng_Latn",
  "enable_local_to_remote": true,
  "enable_remote_to_local": true,
  "enable_tts": true
}
```

响应参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| session_id | string | 会话 ID |
| session_state | string | 会话状态 |
| started_at | string | 启动时间 |

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Session started",
  "data": {
    "session_id": "ses_01HZXABC",
    "session_state": "running",
    "started_at": "2026-06-09T10:01:00+08:00"
  },
  "request_id": "req_session_start_001",
  "protocol_version": "1.0"
}
```

### 3.7 暂停会话

接口地址：`/core/session/pause`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |

示例请求：

```json
{
  "session_id": "ses_01HZXABC"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Session paused",
  "data": {
    "session_id": "ses_01HZXABC",
    "session_state": "paused"
  },
  "request_id": "req_session_pause_001",
  "protocol_version": "1.0"
}
```

### 3.8 恢复会话

接口地址：`/core/session/resume`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |

示例请求：

```json
{
  "session_id": "ses_01HZXABC"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Session resumed",
  "data": {
    "session_id": "ses_01HZXABC",
    "session_state": "running"
  },
  "request_id": "req_session_resume_001",
  "protocol_version": "1.0"
}
```

### 3.9 停止会话

接口地址：`/core/session/stop`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |
| save_history | boolean | 否 | 是否按当前配置保存历史 |

示例请求：

```json
{
  "session_id": "ses_01HZXABC",
  "save_history": false
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Session stopped",
  "data": {
    "session_id": "ses_01HZXABC",
    "session_state": "idle",
    "released_devices": true,
    "history_saved": false
  },
  "request_id": "req_session_stop_001",
  "protocol_version": "1.0"
}
```

### 3.10 查询历史列表

接口地址：`/core/history/list`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| offset | number | 否 | 起始位置，默认 0 |
| limit | number | 否 | 条数，默认 20 |

示例请求：

```text
GET /core/history/list?offset=0&limit=20
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "items": [
      {
        "session_id": "ses_01HZXABC",
        "started_at": "2026-06-09T10:01:00+08:00",
        "ended_at": "2026-06-09T10:31:00+08:00",
        "local_lang": "cmn_Hans",
        "remote_lang": "eng_Latn",
        "has_recording": false,
        "has_transcript": true,
        "has_translation": true
      }
    ],
    "total": 1
  },
  "request_id": "req_history_list_001",
  "protocol_version": "1.0"
}
```

### 3.11 删除历史

接口地址：`/core/history/delete`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |

示例请求：

```json
{
  "session_id": "ses_01HZXABC"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "History deleted",
  "data": {
    "session_id": "ses_01HZXABC",
    "deleted_recording": false,
    "deleted_transcript": true,
    "deleted_translation": true
  },
  "request_id": "req_history_delete_001",
  "protocol_version": "1.0"
}
```

### 3.12 导出诊断信息

接口地址：`/core/diagnostics/export`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| include_text | boolean | 否 | 是否包含文本内容，默认 false |
| include_audio | boolean | 否 | 是否包含音频内容，默认 false |

示例请求：

```json
{
  "include_text": false,
  "include_audio": false
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Diagnostics exported",
  "data": {
    "file_path": "D:/Users/example/AppData/Local/open-lingua-bridge/diagnostics/diag_20260609.zip",
    "include_text": false,
    "include_audio": false
  },
  "request_id": "req_diag_export_001",
  "protocol_version": "1.0"
}
```

## 4. Rust Core -> Python Model Service 接口

以下接口为本地 HTTP API，仅允许 Rust Core 或开发调试工具访问。

### 4.1 健康检查

接口地址：`/health`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| include_models | boolean | 否 | 是否返回模型状态 |

示例请求：

```text
GET /health?include_models=true
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "service_status": "ready",
    "service_version": "0.1.0",
    "protocol_version": "1.0",
    "device": {
      "type": "cpu",
      "available": true
    },
    "models": {
      "asr": "not_loaded",
      "vad": "not_loaded",
      "translate": "not_loaded",
      "tts": "not_loaded"
    }
  },
  "request_id": "req_health_001",
  "protocol_version": "1.0"
}
```

### 4.2 查询模型列表

接口地址：`/models`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| provider | string | 否 | `asr`、`vad`、`translate`、`tts` |
| include_status | boolean | 否 | 是否包含加载状态 |

示例请求：

```text
GET /models?provider=asr&include_status=true
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "models": [
      {
        "provider": "asr",
        "name": "faster-whisper-small",
        "path": "D:/models/faster-whisper-small",
        "languages": ["auto", "eng", "zh"],
        "status": "available",
        "loaded": false
      }
    ]
  },
  "request_id": "req_models_001",
  "protocol_version": "1.0"
}
```

### 4.3 查询 TTS voices

接口地址：`/voices`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| language | string | 否 | 目标语言，例如 `eng_Latn` |
| include_license | boolean | 否 | 是否返回授权信息 |

示例请求：

```text
GET /voices?language=eng_Latn&include_license=true
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "voices": [
      {
        "id": "en_US-lessac-medium",
        "provider": "piper",
        "language": "eng_Latn",
        "model_path": "D:/models/piper/en_US-lessac-medium.onnx",
        "config_path": "D:/models/piper/en_US-lessac-medium.onnx.json",
        "sample_rate": 22050,
        "speakers": [0],
        "license": "see MODEL_CARD"
      }
    ]
  },
  "request_id": "req_voices_001",
  "protocol_version": "1.0"
}
```

### 4.4 校验语言链路

接口地址：`/language-chain/check`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| source_lang | string | 是 | 源语言 |
| target_lang | string | 是 | 目标语言 |
| require_tts | boolean | 是 | 是否要求 TTS 可用 |

示例请求：

```json
{
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn",
  "require_tts": true
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Language chain is complete",
  "data": {
    "complete": true,
    "asr_supported": true,
    "translate_supported": true,
    "tts_supported": true,
    "missing": []
  },
  "request_id": "req_lang_chain_001",
  "protocol_version": "1.0"
}
```

### 4.5 加载模型

接口地址：`/models/load`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| providers | array | 是 | 需要加载的 Provider |
| config | object | 是 | 模型配置 |

示例请求：

```json
{
  "providers": ["vad", "asr", "translate", "tts"],
  "config": {
    "vad": {
      "provider": "silero-vad",
      "sample_rate": 16000
    },
    "asr": {
      "provider": "faster-whisper",
      "model_path": "D:/models/faster-whisper-small",
      "device": "cpu",
      "compute_type": "int8"
    },
    "translate": {
      "provider": "nllb",
      "model_path": "D:/models/nllb-200-distilled-600M"
    },
    "tts": {
      "provider": "piper",
      "voice_path": "D:/models/piper/en_US-lessac-medium.onnx"
    }
  }
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Models loaded",
  "data": {
    "loaded": ["vad", "asr", "translate", "tts"],
    "failed": []
  },
  "request_id": "req_models_load_001",
  "protocol_version": "1.0"
}
```

### 4.6 模型热身

接口地址：`/models/warmup`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| providers | array | 是 | 需要热身的 Provider |
| source_lang | string | 是 | 源语言 |
| target_lang | string | 是 | 目标语言 |

示例请求：

```json
{
  "providers": ["asr", "translate", "tts"],
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Warmup completed",
  "data": {
    "results": [
      { "provider": "asr", "success": true, "latency_ms": 520 },
      { "provider": "translate", "success": true, "latency_ms": 180 },
      { "provider": "tts", "success": true, "latency_ms": 240 }
    ]
  },
  "request_id": "req_warmup_001",
  "protocol_version": "1.0"
}
```

### 4.7 创建后端会话

接口地址：`/sessions/start`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | Rust Core 生成的会话 ID |
| local_lang | string | 是 | 本方语言 |
| remote_lang | string | 是 | 对方语言 |
| directions | array | 是 | 启用方向 |

示例请求：

```json
{
  "session_id": "ses_01HZXABC",
  "local_lang": "cmn_Hans",
  "remote_lang": "eng_Latn",
  "directions": ["local_to_remote", "remote_to_local"]
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Backend session started",
  "data": {
    "session_id": "ses_01HZXABC",
    "state": "running",
    "started_at": "2026-06-09T10:01:00+08:00"
  },
  "request_id": "req_backend_session_start_001",
  "protocol_version": "1.0"
}
```

### 4.8 暂停后端会话

接口地址：`/sessions/pause`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |

示例请求：

```json
{
  "session_id": "ses_01HZXABC"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Backend session paused",
  "data": {
    "session_id": "ses_01HZXABC",
    "state": "paused"
  },
  "request_id": "req_backend_session_pause_001",
  "protocol_version": "1.0"
}
```

### 4.9 恢复后端会话

接口地址：`/sessions/resume`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |

示例请求：

```json
{
  "session_id": "ses_01HZXABC"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Backend session resumed",
  "data": {
    "session_id": "ses_01HZXABC",
    "state": "running"
  },
  "request_id": "req_backend_session_resume_001",
  "protocol_version": "1.0"
}
```

### 4.10 停止后端会话

接口地址：`/sessions/stop`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 是 | 会话 ID |
| flush | boolean | 否 | 是否执行最终 flush |

示例请求：

```json
{
  "session_id": "ses_01HZXABC",
  "flush": true
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "Backend session stopped",
  "data": {
    "session_id": "ses_01HZXABC",
    "state": "stopped",
    "flushed": true
  },
  "request_id": "req_backend_session_stop_001",
  "protocol_version": "1.0"
}
```

### 4.11 ASR 单阶段测试

接口地址：`/test/asr`

请求方法：`POST`

请求参数：JSON body。

说明：该接口只用于测试小样本音频路径，不用于实时链路。`audio_file_path` 必须是 Python 服务可访问的本地文件路径。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| audio_file_path | string | 是 | 本地音频文件路径 |
| language | string | 否 | ASR 语言 |

示例请求：

```json
{
  "audio_file_path": "D:/test/audio/hello.wav",
  "language": "eng"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "text": "Hello, nice to meet you.",
    "language": "eng",
    "confidence": 0.92,
    "latency_ms": 430
  },
  "request_id": "req_test_asr_001",
  "protocol_version": "1.0"
}
```

### 4.12 翻译单阶段测试

接口地址：`/test/translate`

请求方法：`POST`

请求参数：JSON body。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| text | string | 是 | 待翻译文本 |
| source_lang | string | 是 | 源语言 |
| target_lang | string | 是 | 目标语言 |

示例请求：

```json
{
  "text": "你好，很高兴认识你。",
  "source_lang": "cmn_Hans",
  "target_lang": "eng_Latn"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "translated_text": "Hello, nice to meet you.",
    "latency_ms": 160
  },
  "request_id": "req_test_translate_001",
  "protocol_version": "1.0"
}
```

### 4.13 TTS 单阶段测试

接口地址：`/test/tts`

请求方法：`POST`

请求参数：JSON body。

说明：返回本地生成文件路径或音频元数据，不在 JSON 中返回大音频二进制内容。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| text | string | 是 | 待合成文本 |
| language | string | 是 | 目标语言 |
| voice_id | string | 是 | voice ID |

示例请求：

```json
{
  "text": "Hello, nice to meet you.",
  "language": "eng_Latn",
  "voice_id": "en_US-lessac-medium"
}
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "audio_file_path": "D:/temp/olb/tts_test_001.wav",
    "sample_rate": 22050,
    "duration_ms": 1850,
    "latency_ms": 240
  },
  "request_id": "req_test_tts_001",
  "protocol_version": "1.0"
}
```

### 4.14 查询后端指标

接口地址：`/metrics`

请求方法：`GET`

请求参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | string | 否 | 会话 ID |

示例请求：

```text
GET /metrics?session_id=ses_01HZXABC
```

示例响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "",
  "data": {
    "session_id": "ses_01HZXABC",
    "queues": {
      "asr_queue_size": 0,
      "translate_queue_size": 0,
      "tts_queue_size": 0
    },
    "latency_ms": {
      "asr_avg": 520,
      "translate_avg": 160,
      "tts_avg": 240
    }
  },
  "request_id": "req_metrics_001",
  "protocol_version": "1.0"
}
```

## 5. 前端订阅事件

Tauri event 不属于 GET/POST 接口，但前端需要通过事件接收 Rust Core 推送的实时状态。

### 5.1 `session_status_changed`

示例事件：

```json
{
  "event": "session_status_changed",
  "data": {
    "session_id": "ses_01HZXABC",
    "session_state": "running",
    "timestamp_ms": 1780000000000
  }
}
```

### 5.2 `subtitle_updated`

示例事件：

```json
{
  "event": "subtitle_updated",
  "data": {
    "session_id": "ses_01HZXABC",
    "stream_id": "audio_local",
    "segment_id": "seg_0001",
    "direction": "local_to_remote",
    "source_text": "你好，很高兴认识你。",
    "translated_text": "Hello, nice to meet you.",
    "is_final": true,
    "timestamp_ms": 1780000000000
  }
}
```

### 5.3 `latency_updated`

示例事件：

```json
{
  "event": "latency_updated",
  "data": {
    "session_id": "ses_01HZXABC",
    "segment_id": "seg_0001",
    "asr_latency_ms": 520,
    "translate_latency_ms": 160,
    "tts_latency_ms": 240,
    "subtitle_e2e_latency_ms": 920,
    "tts_e2e_latency_ms": 1250
  }
}
```

### 5.4 `error_occurred`

示例事件：

```json
{
  "event": "error_occurred",
  "data": {
    "session_id": "ses_01HZXABC",
    "code": "AUDIO_DEVICE_UNAVAILABLE",
    "message": "Selected microphone is unavailable",
    "recoverable": true,
    "timestamp_ms": 1780000000000
  }
}
```

## 6. 实时数据面说明

本文档按要求只定义 GET 和 POST 接口。实时音频链路不使用 GET/POST 承载音频内容。

实时链路使用：

```text
WS /ws/session
```

用途：

- `audio.frame`：Rust Core 发送音频帧给 Python Model Service。
- `asr.partial`：Python Model Service 返回 ASR 临时结果。
- `asr.final`：Python Model Service 返回 ASR 最终结果。
- `translate.result`：Python Model Service 返回翻译结果。
- `tts.audio`：Python Model Service 返回 TTS 音频。
- `status.update`：状态更新。
- `error`：错误事件。

约束：

- 音频大负载使用 binary frame。
- JSON 只传 metadata，不传大音频内容。
- 每条消息都需要包含 `protocol_version`、`session_id`、`stream_id`、`segment_id`、`sequence_no`。

## 7. 接口变更策略

- `protocol_version` 从 `1.0` 开始。
- 新增字段必须保持向后兼容。
- 删除字段或修改字段语义需要提升协议版本。
- Rust Core 与 Python Model Service 版本不兼容时，返回 `PROTOCOL_VERSION_MISMATCH`。
- 前端 UI 应展示协议不兼容错误，并提示用户重启或升级组件。
