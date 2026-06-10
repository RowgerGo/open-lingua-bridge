import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { UnlistenFn } from "@tauri-apps/api/event";

type StatusResponse = {
  protocol_version?: string;
  session_state?: string;
  backend_status?: string;
  current_session_id?: string | null;
  error?: string | null;
};

type CoreConfig = {
  backend?: {
    base_url?: string;
    auth_token?: string;
    client_name?: string;
  };
  privacy?: {
    save_recording?: boolean;
    save_transcript?: boolean;
    save_translation?: boolean;
  };
};

type AudioDeviceInfo = {
  id: string;
  name: string;
  kind: "input" | "output";
  is_default: boolean;
};

type AudioDevices = {
  inputs: AudioDeviceInfo[];
  outputs: AudioDeviceInfo[];
};

type EventPayload = Record<string, unknown>;

type PrecheckItem = {
  label: string;
  ok: boolean;
  detail: string;
  blocking: boolean;
};

type LatencyMetrics = {
  asrMs: number | null;
  translateMs: number | null;
  ttsMs: number | null;
  e2eMs: number | null;
  queueDepth: number;
};

type DiagnosticSnapshot = {
  generated_at: string;
  protocol_version: string;
  backend_status: string;
  session_state: string;
  current_session_id: string;
  language_direction: string;
  audio_format: string;
  selected_devices: Record<string, string>;
  backend_base_url: string;
  privacy: Record<string, boolean>;
  model_configured: Record<string, boolean>;
  metrics: LatencyMetrics;
  event_count: number;
  last_error: string;
  transcript_count: number;
  translation_count: number;
  transcript_content_included: false;
  translation_content_included: false;
};

type RuntimePrecheckResponse = {
  ok: boolean;
  code: string;
  message: string;
  loaded: string[];
  failed: string[];
};

const eventNames = [
  "olb://backend",
  "olb://audio",
  "olb://session",
  "olb://transcript",
  "olb://translation",
  "olb://tts",
  "olb://error",
] as const;

const storageKey = "olb.desktop.p5.settings";

const backendPill = requireElement<HTMLDivElement>("#backend-pill");
const backendStatus = requireElement<HTMLElement>("#backend-status");
const sessionState = requireElement<HTMLElement>("#session-state");
const sessionId = requireElement<HTMLElement>("#session-id");
const protocolVersion = requireElement<HTMLElement>("#protocol-version");
const audioFormat = requireElement<HTMLElement>("#audio-format");
const modelStatus = requireElement<HTMLElement>("#model-status");
const languageDirection = requireElement<HTMLElement>("#language-direction");
const privacyStatus = requireElement<HTMLElement>("#privacy-status");
const precheckSummary = requireElement<HTMLElement>("#precheck-summary");
const precheckList = requireElement<HTMLUListElement>("#precheck-list");
const errorOutput = requireElement<HTMLDivElement>("#error-output");
const transcriptList = requireElement<HTMLDivElement>("#transcript-list");
const translationList = requireElement<HTMLDivElement>("#translation-list");
const eventList = requireElement<HTMLDivElement>("#event-list");
const transcriptCount = requireElement<HTMLElement>("#transcript-count");
const translationCount = requireElement<HTMLElement>("#translation-count");
const asrLatency = requireElement<HTMLElement>("#asr-latency");
const translateLatency = requireElement<HTMLElement>("#translate-latency");
const ttsLatency = requireElement<HTMLElement>("#tts-latency");
const e2eLatency = requireElement<HTMLElement>("#e2e-latency");
const diagnosticStatus = requireElement<HTMLElement>("#diagnostic-status");
const eventCountLabel = requireElement<HTMLElement>("#event-count");

const controls = {
  start: requireElement<HTMLButtonElement>("#start-button"),
  audioStart: requireElement<HTMLButtonElement>("#audio-start-button"),
  pause: requireElement<HTMLButtonElement>("#pause-button"),
  resume: requireElement<HTMLButtonElement>("#resume-button"),
  stop: requireElement<HTMLButtonElement>("#stop-button"),
  precheck: requireElement<HTMLButtonElement>("#precheck-button"),
  status: requireElement<HTMLButtonElement>("#status-button"),
  devices: requireElement<HTMLButtonElement>("#devices-button"),
  saveConfig: requireElement<HTMLButtonElement>("#save-config-button"),
  swapLanguage: requireElement<HTMLButtonElement>("#swap-language-button"),
  recover: requireElement<HTMLButtonElement>("#recover-button"),
  clearEvents: requireElement<HTMLButtonElement>("#clear-events-button"),
  exportDiagnostics: requireElement<HTMLButtonElement>("#export-diagnostics-button"),
  copyDiagnostics: requireElement<HTMLButtonElement>("#copy-diagnostics-button"),
};

const fields = {
  localInput: requireElement<HTMLSelectElement>("#local-input-device"),
  remoteInput: requireElement<HTMLSelectElement>("#remote-input-device"),
  output: requireElement<HTMLSelectElement>("#output-device"),
  virtualOutput: requireElement<HTMLSelectElement>("#virtual-output-device"),
  localLanguage: requireElement<HTMLSelectElement>("#local-language"),
  remoteLanguage: requireElement<HTMLSelectElement>("#remote-language"),
  backendBaseUrl: requireElement<HTMLInputElement>("#backend-base-url"),
  authToken: requireElement<HTMLInputElement>("#auth-token"),
  vadModelPath: requireElement<HTMLInputElement>("#vad-model-path"),
  asrModelPath: requireElement<HTMLInputElement>("#asr-model-path"),
  translateModelPath: requireElement<HTMLInputElement>("#translate-model-path"),
  ttsVoice: requireElement<HTMLInputElement>("#tts-voice"),
  saveRecording: requireElement<HTMLInputElement>("#save-recording"),
  saveTranscript: requireElement<HTMLInputElement>("#save-transcript"),
  saveTranslation: requireElement<HTMLInputElement>("#save-translation"),
};

const metrics: LatencyMetrics = {
  asrMs: null,
  translateMs: null,
  ttsMs: null,
  e2eMs: null,
  queueDepth: 0,
};

let transcriptTotal = 0;
let translationTotal = 0;
let eventTotal = 0;
let lastError = "";
let savedDeviceSelection: Record<string, string> = {
  localInput: "",
  remoteInput: "",
  output: "",
  virtualOutput: "",
};

controls.start.addEventListener("click", () => {
  startCheckedSession(false).catch((error) => showBackendError(error));
});
controls.audioStart.addEventListener("click", () => {
  startCheckedSession(true).catch((error) => showBackendError(error));
});
controls.pause.addEventListener("click", () => runCommand("pause_session", "正在暂停会话..."));
controls.resume.addEventListener("click", () => runCommand("resume_session", "正在恢复会话..."));
controls.stop.addEventListener("click", () => runCommand("stop_session", "正在停止会话..."));
controls.precheck.addEventListener("click", () => {
  runPrecheck(true).catch((error) => showBackendError(error));
});
controls.status.addEventListener("click", () => refreshStatus());
controls.devices.addEventListener("click", () => refreshAudioDevices());
controls.saveConfig.addEventListener("click", () => saveConfig());
controls.swapLanguage.addEventListener("click", () => swapLanguages());
controls.recover.addEventListener("click", () => recoverFromError());
controls.clearEvents.addEventListener("click", () => clearRuntimeEvents());
controls.exportDiagnostics.addEventListener("click", () => exportDiagnostics());
controls.copyDiagnostics.addEventListener("click", () => copyDiagnostics());

for (const field of Object.values(fields)) {
  field.addEventListener("change", () => {
    updateDerivedUi();
    persistUiSettings();
  });
}

initialize().catch((error) => showBackendError(error));

async function initialize(): Promise<void> {
  loadUiSettings();
  updateDerivedUi();
  renderPrecheck(runPrecheckItems());
  await registerEventListeners();
  await loadConfig();
  await refreshStatus();
  await refreshAudioDevices();
}

async function loadConfig(): Promise<void> {
  try {
    const config = await invoke<CoreConfig>("get_config");
    if (config.backend?.base_url) {
      fields.backendBaseUrl.value = config.backend.base_url;
    }
    if (config.backend?.auth_token) {
      fields.authToken.value = config.backend.auth_token;
    }
    fields.saveRecording.checked = config.privacy?.save_recording === true;
    fields.saveTranscript.checked = config.privacy?.save_transcript === true;
    fields.saveTranslation.checked = config.privacy?.save_translation === true;
    updateDerivedUi();
    persistUiSettings();
  } catch (error) {
    showBackendError(error);
  }
}

async function saveConfig(): Promise<void> {
  setControlsDisabled(true);
  showNotice("正在保存本地配置...", "ok");
  try {
    await invoke<CoreConfig>("update_config", {
      update: {
        backend_base_url: fields.backendBaseUrl.value.trim(),
        auth_token: fields.authToken.value,
        runtime: runtimeConfig(),
        save_recording: fields.saveRecording.checked,
        save_transcript: fields.saveTranscript.checked,
        save_translation: fields.saveTranslation.checked,
      },
    });
    persistUiSettings();
    updateDerivedUi();
    renderPrecheck(runPrecheckItems());
    showNotice("配置已保存。语言、模型路径和 TTS voice 已同步到 Rust 运行时配置，并会在启动前通过本地模型服务预检。", "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function refreshStatus(): Promise<void> {
  setControlsDisabled(true);
  try {
    const status = await invoke<StatusResponse>("get_status");
    renderStatus(status);
    if (!status.error) {
      showNotice("状态已刷新。", "ok");
    }
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function refreshAudioDevices(): Promise<void> {
  setControlsDisabled(true);
  showNotice("正在枚举音频设备...", "ok");
  try {
    const previous = preferredDeviceSelection();
    const devices = await invoke<AudioDevices>("get_audio_devices");
    renderAudioDevices(devices, previous);
    renderPrecheck(runPrecheckItems());
    showNotice(`已发现 ${devices.inputs.length} 个输入设备、${devices.outputs.length} 个输出设备。`, "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function startCheckedSession(withAudio: boolean): Promise<void> {
  const precheck = runPrecheckItems();
  renderPrecheck(precheck);
  const blockers = precheck.filter((item) => item.blocking && !item.ok);
  if (blockers.length > 0) {
    const details = blockers.map((item) => `- ${item.label}: ${item.detail}`).join("\n");
    showNotice(`启动前预检未通过，已阻止启动。\n${details}`, "error");
    return;
  }

  const backendPrecheck = await runBackendPrecheck();
  if (!backendPrecheck.ok) {
    showNotice(`启动前模型预检失败，已阻止启动。\n类型：${backendPrecheck.code}\n详情：${backendPrecheck.message}\n失败项：${backendPrecheck.failed.join(", ") || "未返回"}`, "error");
    return;
  }

  if (withAudio) {
    await startAudioSession();
  } else {
    await runCommand("start_session", "正在开始会话...");
  }
}

async function startAudioSession(): Promise<void> {
  setControlsDisabled(true);
  showNotice("正在启动真实音频链路...", "ok");
  try {
    const status = await invoke<StatusResponse>("start_audio_session", {
      request: {
        local_input_device_id: selectedValue(fields.localInput),
        remote_input_device_id: selectedValue(fields.remoteInput),
        output_device_id: selectedValue(fields.output),
        virtual_microphone_device_id: selectedValue(fields.virtualOutput),
        runtime: runtimeConfig(),
      },
    });
    renderStatus(status);
    showNotice("音频链路已启动，采集帧、字幕、TTS 和错误状态会进入事件流。", "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function runCommand(command: string, message: string): Promise<void> {
  setControlsDisabled(true);
  showNotice(message, "ok");
  try {
    const status = await invoke<StatusResponse>(command);
    renderStatus(status);
    showNotice(`操作完成：${localizeSessionState(status.session_state ?? "unknown")}`, "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function recoverFromError(): Promise<void> {
  clearRuntimeEvents();
  await refreshStatus();
  renderPrecheck(runPrecheckItems());
}

async function runPrecheck(showResult = false): Promise<PrecheckItem[]> {
  const items = runPrecheckItems();
  renderPrecheck(items);
  if (showResult) {
    const failed = items.filter((item) => item.blocking && !item.ok).length;
    if (failed > 0) {
      showNotice(`预检发现 ${failed} 个阻塞项，请先修正配置。`, "error");
      return items;
    }
    const backendPrecheck = await runBackendPrecheck();
    showNotice(
      backendPrecheck.ok
        ? `本地模型服务预检通过，已加载：${backendPrecheck.loaded.join(", ") || "未返回加载列表"}。`
        : `本地模型服务预检失败：${backendPrecheck.code} ${backendPrecheck.message}`,
      backendPrecheck.ok ? "ok" : "error",
    );
  }
  return items;
}

async function runBackendPrecheck(): Promise<RuntimePrecheckResponse> {
  setControlsDisabled(true);
  try {
    return await invoke<RuntimePrecheckResponse>("precheck_runtime_config", { runtime: runtimeConfig() });
  } finally {
    setControlsDisabled(false);
  }
}

function runtimeConfig(): Record<string, string> {
  return {
    local_language: fields.localLanguage.value.trim(),
    remote_language: fields.remoteLanguage.value.trim(),
    vad_model_path: fields.vadModelPath.value.trim(),
    asr_model_path: fields.asrModelPath.value.trim(),
    translate_model_path: fields.translateModelPath.value.trim(),
    tts_voice: fields.ttsVoice.value.trim(),
  };
}

function runPrecheckItems(): PrecheckItem[] {
  const backendUrl = fields.backendBaseUrl.value.trim();
  const token = fields.authToken.value.trim();
  const localLanguage = fields.localLanguage.value;
  const remoteLanguage = fields.remoteLanguage.value;
  const modelPaths = [
    fields.vadModelPath.value.trim(),
    fields.asrModelPath.value.trim(),
    fields.translateModelPath.value.trim(),
  ];
  const ttsVoice = fields.ttsVoice.value.trim();
  return [
    {
      label: "本地后端地址",
      ok: backendUrl.startsWith("http://127.0.0.1") || backendUrl.startsWith("http://localhost"),
      detail: "MVP 要求连接本地 Python Model Service，例如 http://127.0.0.1:8765。",
      blocking: true,
    },
    {
      label: "本地 token",
      ok: token.length > 0,
      detail: "Rust Core 调用本地模型服务需要 token。",
      blocking: true,
    },
    {
      label: "语言方向",
      ok: localLanguage !== remoteLanguage,
      detail: "本方语言和对方语言应不同，避免翻译方向不明确。",
      blocking: true,
    },
    {
      label: "模型路径",
      ok: modelPaths.every((path) => path.length > 0),
      detail: "请填写 VAD、ASR 和翻译模型路径；真实文件校验由 Python Model Service 完成。",
      blocking: true,
    },
    {
      label: "TTS voice",
      ok: ttsVoice.length > 0,
      detail: "请填写本地 Piper voice 或可用 voice 名称。",
      blocking: true,
    },
    {
      label: "隐私默认",
      ok: !fields.saveRecording.checked && !fields.saveTranscript.checked && !fields.saveTranslation.checked,
      detail: "默认不保存录音、转写文本和翻译文本；如开启请确认符合你的使用场景。",
      blocking: false,
    },
  ];
}

function renderPrecheck(items: PrecheckItem[]): void {
  precheckList.replaceChildren();
  const failedBlocking = items.filter((item) => item.blocking && !item.ok).length;
  precheckSummary.textContent = failedBlocking === 0 ? "通过" : `${failedBlocking} 个阻塞项`;
  modelStatus.textContent = failedBlocking === 0 ? "配置就绪" : "待补配置";
  for (const item of items) {
    const element = document.createElement("li");
    const tone = item.ok ? "ok" : item.blocking ? "error" : "warning";
    element.className = `precheck-item ${tone}`;
    element.textContent = `${item.ok ? "通过" : item.blocking ? "阻塞" : "提醒"} · ${item.label}：${item.detail}`;
    precheckList.append(element);
  }
}

async function registerEventListeners(): Promise<void> {
  const unlisteners: UnlistenFn[] = [];
  for (const eventName of eventNames) {
    const unlisten = await listen<unknown>(eventName, (event) => {
      const payload = normalizePayload(event.payload);
      const data = unwrapRealtimePayload(payload);
      eventTotal += 1;
      eventCountLabel.textContent = String(eventTotal);
      updateMetricsFromEvent(eventName, data);

      if (eventName === "olb://transcript") {
        renderSubtitle(transcriptList, data, "transcript");
      } else if (eventName === "olb://translation") {
        renderSubtitle(translationList, data, "translation");
      } else {
        renderRealtimeEvent(findString(payload, ["event_name"]) ?? eventName, data);
      }

      if (eventName === "olb://backend") {
        applyBackendEvent(data);
      }
      if (eventName === "olb://session") {
        applySessionEvent(data);
      }
      if (eventName === "olb://audio") {
        applyAudioEvent(data);
      }
      if (eventName === "olb://error") {
        showEventError(data);
      }
    });
    unlisteners.push(unlisten);
  }

  window.addEventListener("beforeunload", () => {
    for (const unlisten of unlisteners) {
      unlisten();
    }
  });
}

function renderAudioDevices(devices: AudioDevices, selected: Record<string, string>): void {
  renderDeviceOptions(fields.localInput, devices.inputs, "默认输入设备", selected.localInput);
  renderDeviceOptions(fields.remoteInput, devices.inputs, "不采集对方音频", selected.remoteInput);
  renderDeviceOptions(fields.output, devices.outputs, "默认输出设备", selected.output);
  renderDeviceOptions(fields.virtualOutput, devices.outputs, "不路由到虚拟麦克风", selected.virtualOutput);
  persistUiSettings();
}

function renderDeviceOptions(select: HTMLSelectElement, devices: AudioDeviceInfo[], placeholder: string, selectedId: string): void {
  select.replaceChildren();
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = placeholder;
  select.append(defaultOption);
  for (const device of devices) {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = `${device.name}${device.is_default ? "（默认）" : ""}`;
    select.append(option);
  }
  select.value = Array.from(select.options).some((option) => option.value === selectedId) ? selectedId : "";
}

function renderStatus(status: StatusResponse): void {
  protocolVersion.textContent = status.protocol_version ?? "-";
  sessionState.textContent = localizeSessionState(status.session_state ?? "unknown");
  backendStatus.textContent = localizeBackendStatus(status.backend_status ?? "unknown");
  backendPill.textContent = `后端：${localizeBackendStatus(status.backend_status ?? "unknown")}`;
  sessionId.textContent = status.current_session_id ?? "未创建";
  if (status.error) {
    showNotice(status.error, "error");
  }
}

function renderSubtitle(target: HTMLDivElement, payload: EventPayload, kind: "transcript" | "translation"): void {
  clearEmptyState(target);
  const direction = findString(payload, ["direction", "stream_id", "streamId"]) ?? "unknown";
  const segmentId = findString(payload, ["segment_id", "segmentId"]) ?? "segment unknown";
  const text = findString(payload, ["text", "transcript", "translation", "result"]) ?? stringifyPayload(payload);
  const timestamp = findNumber(payload, ["timestamp_ms", "timestampMs"]);
  const title = `${localizeDirection(direction)} · ${segmentId}`;
  const time = timestamp ? formatEventTime(timestamp) : formatTime();
  target.prepend(createEventItem({ title, time, text }));
  if (kind === "transcript") {
    transcriptTotal += 1;
    transcriptCount.textContent = String(transcriptTotal);
  } else {
    translationTotal += 1;
    translationCount.textContent = String(translationTotal);
  }
}

function renderRealtimeEvent(eventName: string, payload: EventPayload): void {
  clearEmptyState(eventList);
  eventList.prepend(createEventItem({ title: eventName, time: formatTime(), text: stringifyPayload(payload) }));
}

function createEventItem(options: { title: string; time: string; text: string }): HTMLDivElement {
  const item = document.createElement("div");
  item.className = "event-item";
  const meta = document.createElement("div");
  meta.className = "event-meta";
  const title = document.createElement("span");
  title.textContent = options.title;
  const time = document.createElement("span");
  time.textContent = options.time;
  meta.append(title, time);
  const text = document.createElement("p");
  text.className = "event-text";
  text.textContent = options.text;
  item.append(meta, text);
  return item;
}

function applyBackendEvent(payload: EventPayload): void {
  const status = findString(payload, ["backend_status", "status", "state"]);
  if (!status) {
    return;
  }
  backendStatus.textContent = localizeBackendStatus(status);
  backendPill.textContent = `后端：${localizeBackendStatus(status)}`;
}

function applySessionEvent(payload: EventPayload): void {
  const state = findString(payload, ["session_state", "state", "status"]);
  const id = findString(payload, ["current_session_id", "session_id", "sessionId"]);
  if (state) {
    sessionState.textContent = localizeSessionState(state);
  }
  if (id) {
    sessionId.textContent = id;
  }
}

function applyAudioEvent(payload: EventPayload): void {
  const sampleRate = findNumber(payload, ["sample_rate", "sampleRate"]);
  const channels = findNumber(payload, ["channels"]);
  const sampleFormat = findString(payload, ["sample_format", "sampleFormat"]);
  if (sampleRate && channels && sampleFormat) {
    audioFormat.textContent = `${sampleRate} Hz / ${channels} ch / ${sampleFormat}`;
  }
}

function updateMetricsFromEvent(eventName: string, payload: EventPayload): void {
  const latency = findNumber(payload, ["latency_ms", "latencyMs", "duration_ms", "durationMs", "processing_ms", "processingMs"]);
  if (latency !== null) {
    if (eventName === "olb://transcript") {
      metrics.asrMs = latency;
    } else if (eventName === "olb://translation") {
      metrics.translateMs = latency;
    } else if (eventName === "olb://tts") {
      metrics.ttsMs = latency;
    } else {
      metrics.e2eMs = latency;
    }
  }
  const queueDepth = findNumber(payload, ["queue_depth", "queueDepth", "pending", "pending_segments"]);
  if (queueDepth !== null) {
    metrics.queueDepth = queueDepth;
  }
  const e2e = findNumber(payload, ["end_to_end_latency_ms", "e2e_latency_ms", "e2eLatencyMs"]);
  if (e2e !== null) {
    metrics.e2eMs = e2e;
  }
  renderMetrics();
}

function renderMetrics(): void {
  asrLatency.textContent = formatLatency(metrics.asrMs);
  translateLatency.textContent = formatLatency(metrics.translateMs);
  ttsLatency.textContent = formatLatency(metrics.ttsMs);
  e2eLatency.textContent = `${formatLatency(metrics.e2eMs)} / ${metrics.queueDepth}`;
}

function showEventError(payload: EventPayload): void {
  const message = findString(payload, ["message", "error", "reason", "detail"]) ?? stringifyPayload(payload);
  const code = findString(payload, ["code", "error_code", "errorCode"]);
  const moduleName = inferErrorModule(code ?? message);
  const suggestion = suggestionForError(code ?? message);
  showNotice(`实时事件错误\n类型：${code ?? "UNKNOWN"}\n模块：${moduleName}\n详情：${message}\n建议：${suggestion}`, "error");
}

function showBackendError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  const moduleName = inferErrorModule(message);
  const suggestion = suggestionForError(message);
  showNotice(`无法连接或调用本地后端\n类型：${extractErrorCode(message)}\n模块：${moduleName}\n详情：${message}\n建议：${suggestion}`, "error");
  backendStatus.textContent = "不可达";
  backendPill.textContent = "后端：不可达";
}

function showNotice(message: string, tone: "ok" | "warning" | "error" = "ok"): void {
  lastError = tone === "error" ? message : lastError;
  errorOutput.textContent = message;
  errorOutput.className = `error-box notice-${tone}`;
}

function clearRuntimeEvents(): void {
  transcriptTotal = 0;
  translationTotal = 0;
  eventTotal = 0;
  transcriptCount.textContent = "0";
  translationCount.textContent = "0";
  eventCountLabel.textContent = "0";
  metrics.asrMs = null;
  metrics.translateMs = null;
  metrics.ttsMs = null;
  metrics.e2eMs = null;
  metrics.queueDepth = 0;
  renderMetrics();
  transcriptList.replaceChildren(emptyState("等待 ASR 原文事件。"));
  translationList.replaceChildren(emptyState("等待翻译结果事件。"));
  eventList.replaceChildren(emptyState("等待实时事件。"));
  showNotice("事件已清空。", "ok");
}

async function exportDiagnostics(): Promise<void> {
  const snapshot = buildDiagnosticSnapshot();
  try {
    const path = await invoke<string>("export_diagnostics", { snapshot });
    diagnosticStatus.textContent = path;
    showNotice(`诊断 JSON 已写入本地日志目录：${path}\n默认不包含录音、转写文本或翻译文本内容。`, "ok");
  } catch (error) {
    downloadDiagnostics(snapshot);
    diagnosticStatus.textContent = `浏览器下载 ${snapshot.generated_at}`;
    showNotice(`本地诊断写入失败，已改为浏览器下载：${String(error)}`, "warning");
  }
}

function downloadDiagnostics(snapshot: DiagnosticSnapshot): void {
  const json = JSON.stringify(snapshot, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `olb-diagnostics-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyDiagnostics(): Promise<void> {
  const snapshot = buildDiagnosticSnapshot();
  const summary = JSON.stringify(snapshot, null, 2);
  try {
    await navigator.clipboard.writeText(summary);
    diagnosticStatus.textContent = `已复制 ${snapshot.generated_at}`;
    showNotice("诊断摘要已复制到剪贴板。", "ok");
  } catch (error) {
    showNotice(`无法复制诊断摘要：${String(error)}`, "warning");
  }
}

function buildDiagnosticSnapshot(): DiagnosticSnapshot {
  return {
    generated_at: new Date().toISOString(),
    protocol_version: protocolVersion.textContent ?? "-",
    backend_status: backendStatus.textContent ?? "unknown",
    session_state: sessionState.textContent ?? "unknown",
    current_session_id: sessionId.textContent ?? "未创建",
    language_direction: languageDirection.textContent ?? "unknown",
    audio_format: audioFormat.textContent ?? "unknown",
    selected_devices: selectedDevices(),
    backend_base_url: fields.backendBaseUrl.value.trim(),
    privacy: {
      save_recording: fields.saveRecording.checked,
      save_transcript: fields.saveTranscript.checked,
      save_translation: fields.saveTranslation.checked,
    },
    model_configured: {
      vad: fields.vadModelPath.value.trim().length > 0,
      asr: fields.asrModelPath.value.trim().length > 0,
      translate: fields.translateModelPath.value.trim().length > 0,
      tts_voice: fields.ttsVoice.value.trim().length > 0,
    },
    metrics: { ...metrics },
    event_count: eventTotal,
    last_error: lastError,
    transcript_count: transcriptTotal,
    translation_count: translationTotal,
    transcript_content_included: false,
    translation_content_included: false,
  };
}

function swapLanguages(): void {
  const localLanguage = fields.localLanguage.value;
  fields.localLanguage.value = fields.remoteLanguage.value;
  fields.remoteLanguage.value = localLanguage;
  updateDerivedUi();
  persistUiSettings();
  renderPrecheck(runPrecheckItems());
}

function updateDerivedUi(): void {
  languageDirection.textContent = `${fields.localLanguage.value} -> ${fields.remoteLanguage.value}`;
  const privacyEnabled = fields.saveRecording.checked || fields.saveTranscript.checked || fields.saveTranslation.checked;
  privacyStatus.textContent = privacyEnabled ? "已开启部分保存" : "不保存录音/文本";
  renderMetrics();
}

function persistUiSettings(): void {
  const settings = {
    selected_devices: selectedDevices(),
    local_language: fields.localLanguage.value,
    remote_language: fields.remoteLanguage.value,
    backend_base_url: fields.backendBaseUrl.value,
    vad_model_path: fields.vadModelPath.value,
    asr_model_path: fields.asrModelPath.value,
    translate_model_path: fields.translateModelPath.value,
    tts_voice: fields.ttsVoice.value,
    save_recording: fields.saveRecording.checked,
    save_transcript: fields.saveTranscript.checked,
    save_translation: fields.saveTranslation.checked,
  };
  localStorage.setItem(storageKey, JSON.stringify(settings));
}

function loadUiSettings(): void {
  const raw = localStorage.getItem(storageKey);
  if (!raw) {
    return;
  }
  const parsed = parseJsonRecord(raw);
  if (!parsed) {
    return;
  }
  const selectedDevicesValue = parsed.selected_devices;
  if (isRecord(selectedDevicesValue)) {
    savedDeviceSelection = {
      localInput: stringField(selectedDevicesValue, "localInput") ?? "",
      remoteInput: stringField(selectedDevicesValue, "remoteInput") ?? "",
      output: stringField(selectedDevicesValue, "output") ?? "",
      virtualOutput: stringField(selectedDevicesValue, "virtualOutput") ?? "",
    };
  }
  setSelectIfOptionExists(fields.localLanguage, stringField(parsed, "local_language") ?? fields.localLanguage.value);
  setSelectIfOptionExists(fields.remoteLanguage, stringField(parsed, "remote_language") ?? fields.remoteLanguage.value);
  fields.backendBaseUrl.value = stringField(parsed, "backend_base_url") ?? fields.backendBaseUrl.value;
  fields.vadModelPath.value = stringField(parsed, "vad_model_path") ?? "";
  fields.asrModelPath.value = stringField(parsed, "asr_model_path") ?? "";
  fields.translateModelPath.value = stringField(parsed, "translate_model_path") ?? "";
  fields.ttsVoice.value = stringField(parsed, "tts_voice") ?? "";
  fields.saveRecording.checked = booleanField(parsed, "save_recording");
  fields.saveTranscript.checked = booleanField(parsed, "save_transcript");
  fields.saveTranslation.checked = booleanField(parsed, "save_translation");
}

function selectedDevices(): Record<string, string> {
  const selection = {
    localInput: fields.localInput.value,
    remoteInput: fields.remoteInput.value,
    output: fields.output.value,
    virtualOutput: fields.virtualOutput.value,
  };
  savedDeviceSelection = selection;
  return selection;
}

function preferredDeviceSelection(): Record<string, string> {
  const current = selectedDevices();
  const hasCurrentSelection = Object.values(current).some((value) => value.length > 0);
  return hasCurrentSelection ? current : savedDeviceSelection;
}

function selectedValue(select: HTMLSelectElement): string | null {
  return select.value.length > 0 ? select.value : null;
}

function setControlsDisabled(disabled: boolean): void {
  for (const control of Object.values(controls)) {
    control.disabled = disabled;
  }
}

function requireElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Missing required element: ${selector}`);
  }
  return element;
}

function clearEmptyState(target: HTMLElement): void {
  const empty = target.querySelector(".empty-state");
  if (empty) {
    empty.remove();
  }
}

function emptyState(text: string): HTMLDivElement {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = text;
  return element;
}

function normalizePayload(payload: unknown): EventPayload {
  if (isRecord(payload)) {
    return payload;
  }
  return { value: payload };
}

function unwrapRealtimePayload(payload: EventPayload): EventPayload {
  const nested = payload.payload;
  if (isRecord(nested)) {
    return nested;
  }
  return payload;
}

function findString(payload: EventPayload, keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return null;
}

function findNumber(payload: EventPayload, keys: string[]): number | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

function isRecord(value: unknown): value is EventPayload {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJsonRecord(raw: string): EventPayload | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function stringField(record: EventPayload, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function booleanField(record: EventPayload, key: string): boolean {
  const value = record[key];
  return value === true;
}

function setSelectIfOptionExists(select: HTMLSelectElement, value: string): void {
  if (Array.from(select.options).some((option) => option.value === value)) {
    select.value = value;
  }
}

function stringifyPayload(payload: EventPayload): string {
  return JSON.stringify(payload, null, 2);
}

function formatTime(): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date());
}

function formatEventTime(timestampMs: number): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(timestampMs));
}

function formatLatency(value: number | null): string {
  return value === null ? "- ms" : `${Math.round(value)} ms`;
}

function localizeSessionState(state: string): string {
  const normalized = state.toLowerCase();
  const labels: Record<string, string> = {
    idle: "未启动",
    starting: "启动中",
    running: "运行中",
    paused: "暂停",
    stopped: "已停止",
    error: "错误",
    unknown: "未知",
  };
  return labels[normalized] ?? state;
}

function localizeBackendStatus(status: string): string {
  const normalized = status.toLowerCase();
  const labels: Record<string, string> = {
    ready: "就绪",
    ok: "就绪",
    healthy: "就绪",
    unreachable: "不可达",
    invalid_config: "配置无效",
    stopped: "已停止",
    unknown: "未知",
  };
  return labels[normalized] ?? status;
}

function localizeDirection(direction: string): string {
  const normalized = direction.toLowerCase();
  if (normalized.includes("local")) {
    return "本方语音";
  }
  if (normalized.includes("remote")) {
    return "对方语音";
  }
  return direction;
}

function extractErrorCode(message: string): string {
  const match = message.match(/[A-Z][A-Z0-9_]{2,}/);
  return match ? match[0] : "UNKNOWN";
}

function inferErrorModule(message: string): string {
  const upper = message.toUpperCase();
  if (upper.includes("AUDIO") || upper.includes("DEVICE") || upper.includes("MIC")) {
    return "音频设备/Rust Core";
  }
  if (upper.includes("MODEL") || upper.includes("ASR") || upper.includes("TRANSLATE") || upper.includes("TTS") || upper.includes("LANGUAGE")) {
    return "Python Model Service";
  }
  if (upper.includes("BACKEND") || upper.includes("WEBSOCKET") || upper.includes("HTTP")) {
    return "后端连接";
  }
  if (upper.includes("SESSION")) {
    return "会话状态机";
  }
  return "桌面端/Rust Core";
}

function suggestionForError(message: string): string {
  const upper = message.toUpperCase();
  if (upper.includes("BACKEND_UNREACHABLE") || upper.includes("UNREACHABLE")) {
    return "启动本地 Python Model Service，并确认后端地址与 token。";
  }
  if (upper.includes("AUDIO_DEVICE") || upper.includes("DEVICE")) {
    return "刷新设备列表，重新选择可用输入/输出设备；虚拟麦克风需由用户自行配置第三方设备。";
  }
  if (upper.includes("MODEL_FILE") || upper.includes("MODEL_LOAD")) {
    return "检查本地模型路径、文件权限和模型格式。";
  }
  if (upper.includes("LANGUAGE_CHAIN")) {
    return "切换语言方向或选择可用的 ASR/翻译/TTS voice 组合。";
  }
  if (upper.includes("SESSION_STATE")) {
    return "刷新状态；如处于错误状态，先停止或恢复后再启动。";
  }
  return "查看链路事件和诊断快照，修正配置后重试。";
}
