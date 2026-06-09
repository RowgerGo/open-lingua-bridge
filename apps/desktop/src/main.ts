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

const eventNames = [
  "olb://backend",
  "olb://audio",
  "olb://session",
  "olb://transcript",
  "olb://translation",
  "olb://tts",
  "olb://error",
] as const;

const backendPill = requireElement<HTMLDivElement>("#backend-pill");
const backendStatus = requireElement<HTMLElement>("#backend-status");
const sessionState = requireElement<HTMLElement>("#session-state");
const sessionId = requireElement<HTMLElement>("#session-id");
const protocolVersion = requireElement<HTMLElement>("#protocol-version");
const audioFormat = requireElement<HTMLElement>("#audio-format");
const errorOutput = requireElement<HTMLDivElement>("#error-output");
const transcriptList = requireElement<HTMLDivElement>("#transcript-list");
const translationList = requireElement<HTMLDivElement>("#translation-list");
const eventList = requireElement<HTMLDivElement>("#event-list");
const transcriptCount = requireElement<HTMLElement>("#transcript-count");
const translationCount = requireElement<HTMLElement>("#translation-count");

const controls = {
  start: requireElement<HTMLButtonElement>("#start-button"),
  audioStart: requireElement<HTMLButtonElement>("#audio-start-button"),
  pause: requireElement<HTMLButtonElement>("#pause-button"),
  resume: requireElement<HTMLButtonElement>("#resume-button"),
  stop: requireElement<HTMLButtonElement>("#stop-button"),
  status: requireElement<HTMLButtonElement>("#status-button"),
  devices: requireElement<HTMLButtonElement>("#devices-button"),
};

const deviceControls = {
  localInput: requireElement<HTMLSelectElement>("#local-input-device"),
  remoteInput: requireElement<HTMLSelectElement>("#remote-input-device"),
  output: requireElement<HTMLSelectElement>("#output-device"),
  virtualOutput: requireElement<HTMLSelectElement>("#virtual-output-device"),
};

let transcriptTotal = 0;
let translationTotal = 0;

controls.start.addEventListener("click", () => runCommand("start_session", "正在开始会话..."));
controls.audioStart.addEventListener("click", () => startAudioSession());
controls.pause.addEventListener("click", () => runCommand("pause_session", "正在暂停会话..."));
controls.resume.addEventListener("click", () => runCommand("resume_session", "正在继续会话..."));
controls.stop.addEventListener("click", () => runCommand("stop_session", "正在停止会话..."));
controls.status.addEventListener("click", () => refreshStatus("正在刷新状态..."));
controls.devices.addEventListener("click", () => refreshAudioDevices());

void registerEventListeners();
void refreshStatus("正在检查本地后端状态...");
void refreshAudioDevices();

function requireElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`缺少页面元素：${selector}`);
  }
  return element;
}

async function runCommand(command: string, pendingMessage: string): Promise<void> {
  setControlsDisabled(true);
  showNotice(pendingMessage);
  try {
    const status = await invoke<StatusResponse>(command);
    renderStatus(status);
    showNotice("操作已发送。P2 阶段实时结果会通过 Rust 事件继续更新。", "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function refreshStatus(pendingMessage: string): Promise<void> {
  setControlsDisabled(true);
  showNotice(pendingMessage);
  try {
    const status = await invoke<StatusResponse>("get_status");
    renderStatus(status);
    if (status.backend_status === "not_connected") {
      showNotice("后端暂未连接：请确认本地 Python Model Service 已启动，并检查配置中的后端地址。", "warning");
    } else if (status.backend_status === "unreachable" && status.error) {
      showNotice(status.error, "error");
    } else {
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
  showNotice("正在枚举音频设备...");
  try {
    const devices = await invoke<AudioDevices>("get_audio_devices");
    renderAudioDevices(devices);
    showNotice(`已发现 ${devices.inputs.length} 个输入设备、${devices.outputs.length} 个输出设备。`, "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function startAudioSession(): Promise<void> {
  setControlsDisabled(true);
  showNotice("正在启动 P3 真实音频链路...");
  try {
    const status = await invoke<StatusResponse>("start_audio_session", {
      request: {
        local_input_device_id: selectedValue(deviceControls.localInput),
        remote_input_device_id: selectedValue(deviceControls.remoteInput),
        output_device_id: selectedValue(deviceControls.output),
        virtual_microphone_device_id: selectedValue(deviceControls.virtualOutput),
      },
    });
    renderStatus(status);
    showNotice("P3 音频链路已启动，采集帧和 TTS 播放状态会进入事件流。", "ok");
  } catch (error) {
    showBackendError(error);
  } finally {
    setControlsDisabled(false);
  }
}

async function registerEventListeners(): Promise<void> {
  const unlisteners: UnlistenFn[] = [];

  for (const eventName of eventNames) {
    const unlisten = await listen<unknown>(eventName, (event) => {
      const payload = normalizePayload(event.payload);
      const data = unwrapRealtimePayload(payload);
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

function renderAudioDevices(devices: AudioDevices): void {
  renderDeviceOptions(deviceControls.localInput, devices.inputs, "默认输入设备");
  renderDeviceOptions(deviceControls.remoteInput, devices.inputs, "不采集对方音频");
  renderDeviceOptions(deviceControls.output, devices.outputs, "默认输出设备");
  renderDeviceOptions(deviceControls.virtualOutput, devices.outputs, "不路由到虚拟麦克风");
  audioFormat.textContent = `16 kHz / mono / pcm_s16le；输入 ${devices.inputs.length}，输出 ${devices.outputs.length}`;
}

function renderDeviceOptions(select: HTMLSelectElement, devices: AudioDeviceInfo[], placeholder: string): void {
  const current = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  for (const device of devices) {
    const label = device.is_default ? `${device.name}（默认）` : device.name;
    select.append(new Option(label, device.id));
  }
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

function renderStatus(status: StatusResponse): void {
  const backend = status.backend_status ?? "unknown";
  backendStatus.textContent = localizeBackendStatus(backend);
  backendPill.textContent = `后端：${localizeBackendStatus(backend)}`;
  sessionState.textContent = localizeSessionState(status.session_state);
  sessionId.textContent = status.current_session_id ?? "无";
  protocolVersion.textContent = status.protocol_version ?? "未知";
  if (status.error) {
    showNotice(status.error, "error");
  }
}

function renderSubtitle(target: HTMLDivElement, payload: EventPayload, kind: "transcript" | "translation"): void {
  clearEmptyState(target);
  const segmentId = findString(payload, ["segment_id", "segmentId", "id"]);
  const text = findString(payload, ["text", "transcript", "translation", "content"]);
  const item = createEventItem({
    title: segmentId ? `segment_id: ${segmentId}` : "segment_id: 未提供",
    time: formatTime(),
    text: text ?? stringifyPayload(payload),
  });
  target.prepend(item);

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
  eventList.prepend(
    createEventItem({
      title: eventName,
      time: formatTime(),
      text: stringifyPayload(payload),
    }),
  );
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

function showEventError(payload: EventPayload): void {
  const message = findString(payload, ["message", "error", "reason", "detail"]);
  showNotice(`实时事件错误：${message ?? stringifyPayload(payload)}`, "error");
}

function showBackendError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  showNotice(`无法连接或调用本地后端：${message}\n请确认 Tauri 后端正在运行；如果是模型服务不可达，请启动本地 Python Model Service 并检查后端地址配置。`, "error");
  backendStatus.textContent = "不可达";
  backendPill.textContent = "后端：不可达";
}

function showNotice(message: string, tone: "ok" | "warning" | "error" = "ok"): void {
  errorOutput.textContent = message;
  const colorByTone = {
    ok: "rgba(126, 224, 184, 0.28)",
    warning: "rgba(255, 209, 102, 0.34)",
    error: "rgba(255, 122, 122, 0.34)",
  } as const;
  errorOutput.style.borderColor = colorByTone[tone];
}

function setControlsDisabled(disabled: boolean): void {
  Object.values(controls).forEach((button) => {
    button.disabled = disabled;
  });
}

function clearEmptyState(target: HTMLElement): void {
  const empty = target.querySelector(".empty-state");
  empty?.remove();
}

function normalizePayload(payload: unknown): EventPayload {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    return payload as EventPayload;
  }
  return { value: payload };
}

function unwrapRealtimePayload(payload: EventPayload): EventPayload {
  const inner = payload.payload;
  if (inner && typeof inner === "object" && !Array.isArray(inner)) {
    return inner as EventPayload;
  }
  return payload;
}

function findString(payload: EventPayload, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const nested = findString(value as EventPayload, keys);
      if (nested) {
        return nested;
      }
    }
  }
  return undefined;
}

function findNumber(payload: EventPayload, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number") {
      return value;
    }
  }
  return undefined;
}

function selectedValue(select: HTMLSelectElement): string | null {
  return select.value === "" ? null : select.value;
}

function stringifyPayload(payload: EventPayload): string {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function localizeBackendStatus(status: string | undefined): string {
  switch (status) {
    case "connected":
      return "已连接";
    case "not_connected":
      return "未连接";
    case "unreachable":
      return "不可达";
    case "unknown":
    case undefined:
      return "未知";
    case "ready":
      return "就绪";
    case "connecting":
      return "连接中";
    case "stopped":
      return "已停止";
    case "invalid_config":
      return "配置无效";
    default:
      return status;
  }
}

function localizeSessionState(state: string | undefined): string {
  switch (state) {
    case "idle":
      return "空闲";
    case "starting":
      return "启动中";
    case "running":
      return "运行中";
    case "paused":
      return "已暂停";
    case "stopped":
      return "已停止";
    case undefined:
      return "未知";
    default:
      return state;
  }
}

function formatTime(): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date());
}
