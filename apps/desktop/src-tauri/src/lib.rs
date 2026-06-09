use olb_core::{CoreConfig, SessionManager, SessionState};
use olb_protocol::PROTOCOL_VERSION;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;

#[derive(Debug, Serialize)]
struct StatusResponse {
    protocol_version: &'static str,
    session_state: SessionState,
    backend_status: String,
    current_session_id: Option<String>,
}

#[tauri::command]
fn get_status(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    status_response(&state, "unknown")
}

#[tauri::command]
fn get_config(state: tauri::State<'_, AppState>) -> Result<CoreConfig, String> {
    let config = state.config.lock().map_err(|err| err.to_string())?;
    Ok(config.clone())
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
fn start_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.start().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "not_connected")
}

#[tauri::command]
fn pause_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.pause().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "not_connected")
}

#[tauri::command]
fn resume_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.resume().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "not_connected")
}

#[tauri::command]
fn stop_session(state: tauri::State<'_, AppState>) -> Result<StatusResponse, String> {
    let mut session = state.session.lock().map_err(|err| err.to_string())?;
    session.stop().map_err(|err| err.to_string())?;
    drop(session);
    status_response(&state, "not_connected")
}

struct AppState {
    session: Mutex<SessionManager>,
    config: Mutex<CoreConfig>,
}

fn status_response(state: &tauri::State<'_, AppState>, backend_status: &str) -> Result<StatusResponse, String> {
    let session = state.session.lock().map_err(|err| err.to_string())?;
    Ok(StatusResponse {
        protocol_version: PROTOCOL_VERSION,
        session_state: session.state(),
        backend_status: backend_status.to_string(),
        current_session_id: session.current_session_id().map(ToOwned::to_owned),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState {
            session: Mutex::new(SessionManager::default()),
            config: Mutex::new(CoreConfig::default()),
        })
        .invoke_handler(tauri::generate_handler![get_status, get_config, update_config, start_session, pause_session, resume_session, stop_session])
        .run(tauri::generate_context!())
        .expect("failed to run app");
}
