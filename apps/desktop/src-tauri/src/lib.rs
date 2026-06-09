use olb_core::{
    capture_audio_frames, default_capture_config, enumerate_audio_devices, run_mock_realtime_smoke_test, run_realtime_audio_smoke_test,
    AudioDevices, AudioError, AudioRouteConfig, CapturedAudioFrame, CoreConfig, ModelServiceClient, RealtimeClientError, RealtimeEvent,
    RealtimeEventKind, SessionManager, SessionState,
};
use olb_protocol::{Direction, ErrorCode, StreamId, PROTOCOL_VERSION};
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter};

#[derive(Debug, Serialize)]
struct StatusResponse {
    protocol_version: &'static str,
    session_state: SessionState,
    backend_status: String,
    current_session_id: Option<String>,
    error: Option<String>,
}

#[tauri::command]
async fn get_status(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let config = config_snapshot(&state)?;
    let backend_status = backend_status(&config).await;
    status_response(&state, &backend_status, None)
}

#[tauri::command]
fn get_config(state: tauri::State<'_, AppState>) -> Result<CoreConfig, String> {
    let config = state.config.lock().map_err(|err| err.to_string())?;
    Ok(config.clone())
}

#[tauri::command]
fn get_audio_devices() -> Result<AudioDevices, String> {
    enumerate_audio_devices().map_err(|err| err.to_string())
}

#[derive(Debug, Deserialize)]
struct AudioSessionRequest {
    local_input_device_id: Option<String>,
    remote_input_device_id: Option<String>,
    output_device_id: Option<String>,
    virtual_microphone_device_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ConfigUpdate {
    backend_base_url: Option<String>,
    auth_token: Option<String>,
    save_recording: Option<bool>,
    save_transcript: Option<bool>,
    save_translation: Option<bool>,
}

#[tauri::command]
fn update_config(state: tauri::State<'_, AppState>, update: ConfigUpdate) -> Result<CoreConfig, String> {
    let mut config = state.config.lock().map_err(|err| err.to_string())?;
    if let Some(base_url) = update.backend_base_url {
        config.backend.base_url = base_url;
    }
    if let Some(auth_token) = update.auth_token {
        config.backend.auth_token = auth_token;
    }
    if let Some(save_recording) = update.save_recording {
        config.privacy.save_recording = save_recording;
    }
    if let Some(save_transcript) = update.save_transcript {
        config.privacy.save_transcript = save_transcript;
    }
    if let Some(save_translation) = update.save_translation {
        config.privacy.save_translation = save_translation;
    }
    Ok(config.clone())
}

#[tauri::command]
async fn start_session(app: AppHandle, state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let session_id = {
        let mut session = state.session.lock().map_err(|err| err.to_string())?;
        if session.state() == SessionState::Error {
            session.reset().map_err(|err| err.to_string())?;
        }
        session.start().map_err(|err| err.to_string())?.to_string()
    };

    let config = config_snapshot(&state)?;
    emit_realtime_event(
        &app,
        &RealtimeEvent {
            kind: RealtimeEventKind::Backend,
            event_name: "backend.connecting".to_string(),
            payload: serde_json::json!({"status": "connecting", "base_url": config.backend.base_url}),
        },
    )?;

    let health_result = match ModelServiceClient::new(&config.backend) {
        Ok(client) => client.health().await.map(|_| ()),
        Err(err) => Err(err),
    };
    if let Err(err) = health_result {
        let message = format!("Python Model Service 不可达：{err}");
        mark_session_failed(&state, ErrorCode::BackendUnreachable)?;
        emit_realtime_event(
            &app,
            &RealtimeEvent {
                kind: RealtimeEventKind::Error,
                event_name: "backend.unreachable".to_string(),
                payload: serde_json::json!({"error_code": "BACKEND_UNREACHABLE", "message": message}),
            },
        )?;
        return status_response(&state, "unreachable", Some(message));
    }

    match run_mock_realtime_smoke_test(&config.backend, &session_id).await {
        Ok(events) => {
            mark_session_running(&state)?;
            emit_realtime_event(
                &app,
                &RealtimeEvent {
                    kind: RealtimeEventKind::Backend,
                    event_name: "backend.ready".to_string(),
                    payload: serde_json::json!({"status": "ready", "base_url": config.backend.base_url}),
                },
            )?;
            for event in events {
                emit_realtime_event(&app, &event)?;
            }
            status_response(&state, "ready", None)
        }
        Err(err) => {
            let message = format!("实时 mock 链路失败：{err}");
            mark_session_failed(&state, ErrorCode::BackendUnreachable)?;
            emit_realtime_event(
                &app,
                &RealtimeEvent {
                    kind: RealtimeEventKind::Error,
                    event_name: "realtime.failed".to_string(),
                    payload: serde_json::json!({"error_code": "BACKEND_UNREACHABLE", "message": message}),
                },
            )?;
            status_response(&state, "unreachable", Some(message))
        }
    }
}

#[tauri::command]
async fn start_audio_session(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
    request: AudioSessionRequest,
) -> Result<StatusResponse, String> {
    let session_id = prepare_session_start(&state)?;
    let config = config_snapshot(&state)?;
    emit_realtime_event(
        &app,
        &RealtimeEvent {
            kind: RealtimeEventKind::Audio,
            event_name: "audio.capture.starting".to_string(),
            payload: serde_json::json!({"session_id": session_id, "sample_rate": 16000, "channels": 1, "sample_format": "pcm_s16le"}),
        },
    )?;

    let health_result = match ModelServiceClient::new(&config.backend) {
        Ok(client) => client.health().await.map(|_| ()),
        Err(err) => Err(err),
    };
    if let Err(err) = health_result {
        let message = format!("Python Model Service 不可达：{err}");
        mark_session_failed(&state, ErrorCode::BackendUnreachable)?;
        emit_error_event(&app, "backend.unreachable", "BACKEND_UNREACHABLE", &message)?;
        return status_response(&state, "unreachable", Some(message));
    }

    let capture_session_id = session_id.clone();
    let capture_result = tokio::task::spawn_blocking(move || {
        let mut audio_frames = Vec::new();
        let mut local_config = default_capture_config(StreamId::AudioLocal, Direction::LocalToRemote);
        local_config.device_id = request.local_input_device_id;
        audio_frames.extend(capture_audio_frames(&local_config, &capture_session_id, 3)?);
        if let Some(remote_device_id) = request.remote_input_device_id {
        let mut remote_config = default_capture_config(StreamId::AudioRemote, Direction::RemoteToLocal);
        remote_config.device_id = Some(remote_device_id);
            audio_frames.extend(capture_audio_frames(&remote_config, &capture_session_id, 3)?);
        }
        normalize_audio_frames(&mut audio_frames);
        Ok::<_, AudioError>(audio_frames)
    })
    .await;

    let audio_frames = match capture_result {
        Ok(Ok(frames)) => frames,
        Ok(Err(err)) => {
            let code = audio_error_code(&err);
            let message = format!("音频采集失败：{err}");
            mark_session_failed(&state, code)?;
            emit_error_event(&app, "audio.capture.failed", error_code_name(code), &message)?;
            return status_response(&state, "audio_error", Some(message));
        }
        Err(err) => {
            let message = format!("音频采集任务失败：{err}");
            mark_session_failed(&state, ErrorCode::AudioCaptureFailed)?;
            emit_error_event(&app, "audio.capture.failed", "AUDIO_CAPTURE_FAILED", &message)?;
            return status_response(&state, "audio_error", Some(message));
        }
    };
    let route = AudioRouteConfig {
        output_device_id: request.output_device_id,
        virtual_microphone_device_id: request.virtual_microphone_device_id,
    };
    match run_realtime_audio_smoke_test(&config.backend, &session_id, audio_frames, Some(route)).await {
        Ok(result) => {
            mark_session_running(&state)?;
            emit_realtime_event(
                &app,
                &RealtimeEvent {
                    kind: RealtimeEventKind::Audio,
                    event_name: "audio.capture.ready".to_string(),
                    payload: serde_json::json!({"session_id": session_id, "sample_rate": 16000, "channels": 1, "sample_format": "pcm_s16le", "playback_status": result.playback_status}),
                },
            )?;
            for event in result.events {
                emit_realtime_event(&app, &event)?;
            }
            status_response(&state, "ready", None)
        }
        Err(err) => {
            let code = realtime_error_code(&err);
            let message = format!("P3 音频链路失败：{err}");
            mark_session_failed(&state, code)?;
            emit_error_event(&app, "audio.pipeline.failed", error_code_name(code), &message)?;
            status_response(&state, "audio_error", Some(message))
        }
    }
}

#[tauri::command]
fn pause_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.pause().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "ready", None)
}

#[tauri::command]
fn resume_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.resume().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "ready", None)
}

#[tauri::command]
fn stop_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.stop().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "stopped", None)
}

fn prepare_session_start(state: &tauri::State<'_, AppState>) -> Result<String, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    if session.state() == SessionState::Error {
        session.reset().map_err(|err| err.to_string())?;
    }
    session.start().map_err(|err| err.to_string()).map(ToOwned::to_owned)
}

struct AppState {
    session: Mutex<SessionManager>,
    config: Mutex<CoreConfig>,
}

fn status_response(state: &tauri::State<'_, AppState>, backend_status: &str, error: Option<String>) -> Result<StatusResponse, String> {
    let session = state.session.lock().map_err(|err| err.to_string())?;
    Ok(StatusResponse {
        protocol_version: PROTOCOL_VERSION,
        session_state: session.state(),
        backend_status: backend_status.to_string(),
        current_session_id: session.current_session_id().map(ToOwned::to_owned),
        error,
    })
}

fn config_snapshot(state: &tauri::State<'_, AppState>) -> Result<CoreConfig, String> {
    let config = state.config.lock().map_err(|err| err.to_string())?;
    Ok(config.clone())
}

async fn backend_status(config: &CoreConfig) -> String {
    match ModelServiceClient::new(&config.backend) {
        Ok(client) if client.health().await.is_ok() => "ready".to_string(),
        Ok(_) => "unreachable".to_string(),
        Err(_) => "invalid_config".to_string(),
    }
}

fn audio_error_code(error: &AudioError) -> ErrorCode {
    match error {
        AudioError::DeviceUnavailable(_) => ErrorCode::AudioDeviceUnavailable,
        AudioError::CaptureFailed(_) => ErrorCode::AudioCaptureFailed,
        AudioError::PlaybackFailed(_) => ErrorCode::TtsRequestFailed,
        AudioError::ResampleFailed(_) => ErrorCode::AudioResampleFailed,
        AudioError::PlaybackQueueOverloaded { .. } => ErrorCode::PlaybackQueueOverloaded,
    }
}

fn realtime_error_code(error: &RealtimeClientError) -> ErrorCode {
    match error {
        RealtimeClientError::AudioPlayback(audio_error) => audio_error_code(audio_error),
        RealtimeClientError::BinaryFrame(_) => ErrorCode::InvalidRequest,
        RealtimeClientError::InvalidUrl(_) | RealtimeClientError::InvalidRequest(_) => ErrorCode::InvalidRequest,
        RealtimeClientError::WebSocket(_) | RealtimeClientError::TimedOut | RealtimeClientError::IncompleteRoundtrip => ErrorCode::BackendUnreachable,
        RealtimeClientError::Json(_) => ErrorCode::InvalidRequest,
    }
}

fn error_code_name(code: ErrorCode) -> &'static str {
    match code {
        ErrorCode::Ok => "OK",
        ErrorCode::InvalidRequest => "INVALID_REQUEST",
        ErrorCode::Unauthorized => "UNAUTHORIZED",
        ErrorCode::ProtocolVersionMismatch => "PROTOCOL_VERSION_MISMATCH",
        ErrorCode::BackendUnreachable => "BACKEND_UNREACHABLE",
        ErrorCode::BackendNotReady => "BACKEND_NOT_READY",
        ErrorCode::AudioDeviceUnavailable => "AUDIO_DEVICE_UNAVAILABLE",
        ErrorCode::AudioPermissionDenied => "AUDIO_PERMISSION_DENIED",
        ErrorCode::AudioCaptureFailed => "AUDIO_CAPTURE_FAILED",
        ErrorCode::AudioResampleFailed => "AUDIO_RESAMPLE_FAILED",
        ErrorCode::ModelFileMissing => "MODEL_FILE_MISSING",
        ErrorCode::ModelLoadFailed => "MODEL_LOAD_FAILED",
        ErrorCode::LanguageChainIncomplete => "LANGUAGE_CHAIN_INCOMPLETE",
        ErrorCode::AsrRequestFailed => "ASR_REQUEST_FAILED",
        ErrorCode::TranslateRequestFailed => "TRANSLATE_REQUEST_FAILED",
        ErrorCode::TtsRequestFailed => "TTS_REQUEST_FAILED",
        ErrorCode::PlaybackQueueOverloaded => "PLAYBACK_QUEUE_OVERLOADED",
        ErrorCode::SessionNotFound => "SESSION_NOT_FOUND",
        ErrorCode::SessionStateInvalid => "SESSION_STATE_INVALID",
        ErrorCode::InternalError => "INTERNAL_ERROR",
    }
}

fn mark_session_running(state: &tauri::State<'_, AppState>) -> Result<(), String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.mark_running().map_err(|err| err.to_string())
}

fn mark_session_failed(state: &tauri::State<'_, AppState>, error: ErrorCode) -> Result<(), String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.fail(error);
    Ok(())
}

fn emit_realtime_event(app: &AppHandle, event: &RealtimeEvent) -> Result<(), String> {
    let name = match event.kind {
        RealtimeEventKind::Backend => "olb://backend",
        RealtimeEventKind::Audio => "olb://audio",
        RealtimeEventKind::Session => "olb://session",
        RealtimeEventKind::Transcript => "olb://transcript",
        RealtimeEventKind::Translation => "olb://translation",
        RealtimeEventKind::Tts => "olb://tts",
        RealtimeEventKind::Error => "olb://error",
    };
    app.emit(name, event).map_err(|err| err.to_string())
}

fn emit_error_event(app: &AppHandle, event_name: &str, error_code: &str, message: &str) -> Result<(), String> {
    emit_realtime_event(
        app,
        &RealtimeEvent {
            kind: RealtimeEventKind::Error,
            event_name: event_name.to_string(),
            payload: serde_json::json!({"error_code": error_code, "message": message}),
        },
    )
}

fn normalize_audio_frames(frames: &mut [CapturedAudioFrame]) {
    for (index, frame) in frames.iter_mut().enumerate() {
        frame.header.sequence_no = (index + 1) as u64;
        frame.header.segment_id = match frame.header.stream_id {
            StreamId::AudioLocal => "seg_000001".to_string(),
            StreamId::AudioRemote => "seg_000002".to_string(),
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use olb_core::PlaybackQueueStatus;
    use olb_protocol::{BinaryFrameHeader, MessageType, SampleFormat, PROTOCOL_VERSION};

    fn frame(stream_id: StreamId, sequence_no: u64) -> CapturedAudioFrame {
        CapturedAudioFrame {
            header: BinaryFrameHeader {
                protocol_version: PROTOCOL_VERSION.to_string(),
                message_type: MessageType::AudioFrame,
                session_id: "ses_test".to_string(),
                stream_id,
                direction: Direction::LocalToRemote,
                segment_id: "seg_old".to_string(),
                sequence_no,
                timestamp_ms: 0,
                source_lang: None,
                target_lang: None,
                sample_rate: 16_000,
                channels: 1,
                sample_format: SampleFormat::PcmS16le,
                duration_ms: 20,
                payload_size: 0,
                is_final: Some(false),
            },
            payload: Vec::new(),
        }
    }

    #[test]
    fn normalizes_mixed_audio_frames_to_single_connection_sequence() {
        let mut frames = vec![frame(StreamId::AudioLocal, 10), frame(StreamId::AudioRemote, 1), frame(StreamId::AudioLocal, 2)];
        normalize_audio_frames(&mut frames);
        assert_eq!(frames[0].header.sequence_no, 1);
        assert_eq!(frames[1].header.sequence_no, 2);
        assert_eq!(frames[2].header.sequence_no, 3);
        assert_eq!(frames[0].header.segment_id, "seg_000001");
        assert_eq!(frames[1].header.segment_id, "seg_000002");
    }

    #[test]
    fn maps_audio_errors_to_public_error_codes() {
        assert_eq!(audio_error_code(&AudioError::DeviceUnavailable("missing".to_string())), ErrorCode::AudioDeviceUnavailable);
        assert_eq!(audio_error_code(&AudioError::CaptureFailed("denied".to_string())), ErrorCode::AudioCaptureFailed);
        assert_eq!(audio_error_code(&AudioError::ResampleFailed("bad rate".to_string())), ErrorCode::AudioResampleFailed);
        assert_eq!(
            audio_error_code(&AudioError::PlaybackQueueOverloaded {
                queued_samples: 4,
                capacity_samples: 2,
            }),
            ErrorCode::PlaybackQueueOverloaded,
        );
    }

    #[test]
    fn maps_playback_errors_from_realtime_pipeline() {
        let error = RealtimeClientError::AudioPlayback(AudioError::PlaybackQueueOverloaded {
            queued_samples: 4,
            capacity_samples: 2,
        });
        assert_eq!(realtime_error_code(&error), ErrorCode::PlaybackQueueOverloaded);
        let _status = PlaybackQueueStatus {
            queued_samples: 0,
            queued_duration_ms: 0,
            capacity_samples: 1,
        };
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState {
            session: Mutex::new(SessionManager::default()),
            config: Mutex::new(CoreConfig::default()),
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            get_config,
            get_audio_devices,
            update_config,
            start_session,
            start_audio_session,
            pause_session,
            resume_session,
            stop_session
        ])
        .run(tauri::generate_context!())
        .expect("failed to run app");
}
