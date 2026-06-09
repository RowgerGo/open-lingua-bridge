use futures_util::{SinkExt, StreamExt};
use olb_protocol::{
    decode_binary_frame, encode_binary_frame, BaseMessage, BinaryFrameHeader, Direction, MessageType, SampleFormat, StreamId,
    PROTOCOL_VERSION, WS_SESSION_PATH,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::time::{timeout, Duration};
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::http::Request;
use tokio_tungstenite::tungstenite::Message;
use url::Url;
use uuid::Uuid;

use crate::config::BackendConfig;
use crate::{play_tts_audio, AudioRouteConfig, CapturedAudioFrame, PlaybackQueueStatus};

const HEADER_AUTH_TOKEN: &str = "X-OLB-Auth-Token";
const HEADER_PROTOCOL_VERSION: &str = "X-OLB-Protocol-Version";
const HEADER_CLIENT: &str = "X-OLB-Client";
const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const ROUNDTRIP_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RealtimeEventKind {
    Backend,
    Audio,
    Session,
    Transcript,
    Translation,
    Tts,
    Error,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RealtimeEvent {
    pub kind: RealtimeEventKind,
    pub event_name: String,
    pub payload: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RealtimeAudioResult {
    pub events: Vec<RealtimeEvent>,
    pub playback_status: Option<PlaybackQueueStatus>,
}

#[derive(Debug, thiserror::Error)]
pub enum RealtimeClientError {
    #[error("invalid backend websocket url: {0}")]
    InvalidUrl(String),
    #[error("invalid websocket request: {0}")]
    InvalidRequest(String),
    #[error("websocket error: {0}")]
    WebSocket(#[from] tokio_tungstenite::tungstenite::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("binary frame error: {0}")]
    BinaryFrame(#[from] olb_protocol::BinaryFrameError),
    #[error("realtime mock smoke test timed out")]
    TimedOut,
    #[error("realtime mock roundtrip did not receive expected translation and TTS events")]
    IncompleteRoundtrip,
    #[error("audio playback error: {0}")]
    AudioPlayback(#[from] crate::AudioError),
}

pub async fn run_mock_realtime_smoke_test(config: &BackendConfig, session_id: &str) -> Result<Vec<RealtimeEvent>, RealtimeClientError> {
    Ok(run_realtime_audio_smoke_test(config, session_id, vec![mock_captured_audio_frame(session_id)], None)
        .await?
        .events)
}

pub async fn run_realtime_audio_smoke_test(
    config: &BackendConfig,
    session_id: &str,
    audio_frames: Vec<CapturedAudioFrame>,
    route: Option<AudioRouteConfig>,
) -> Result<RealtimeAudioResult, RealtimeClientError> {
    let request = build_ws_request(config)?;
    let (mut socket, _) = timeout(CONNECT_TIMEOUT, connect_async(request)).await.map_err(|_| RealtimeClientError::TimedOut)??;
    let mut events = Vec::new();
    let mut playback_status = None;

    socket.send(Message::Text(session_start_message(session_id)?)).await?;

    for audio_frame in audio_frames {
        let frame = encode_binary_frame(&audio_frame.header, &audio_frame.payload)?;
        socket.send(Message::Binary(frame)).await?;
    }

    let mut saw_translation = false;
    let mut saw_tts = false;
    let receive_result = timeout(ROUNDTRIP_TIMEOUT, async {
        while let Some(message) = socket.next().await {
            match message? {
                Message::Text(text) => {
                    let event = text_to_event(&text)?;
                    if event.event_name == "translate.result" {
                        saw_translation = true;
                    }
                    events.push(event);
                }
                Message::Binary(bytes) => {
                    let frame = decode_binary_frame(&bytes)?;
                    saw_tts = frame.header.message_type == MessageType::TtsAudio;
                    if let Some(route) = &route {
                        let route = route.clone();
                        let payload = frame.payload.clone();
                        let sample_rate = frame.header.sample_rate;
                        let channels = frame.header.channels;
                        playback_status = Some(
                            tokio::task::spawn_blocking(move || play_tts_audio(&route, &payload, sample_rate, channels))
                                .await
                                .map_err(|err| RealtimeClientError::AudioPlayback(crate::AudioError::PlaybackFailed(err.to_string())))??,
                        );
                    }
                    events.push(RealtimeEvent {
                        kind: RealtimeEventKind::Tts,
                        event_name: "tts.audio".to_string(),
                        payload: json!({
                            "protocol_version": frame.header.protocol_version,
                            "type": "tts.audio",
                            "session_id": frame.header.session_id,
                            "segment_id": frame.header.segment_id,
                            "sequence_no": frame.header.sequence_no,
                            "sample_rate": frame.header.sample_rate,
                            "channels": frame.header.channels,
                            "sample_format": frame.header.sample_format,
                            "payload_size": frame.payload.len()
                        }),
                    });
                }
                Message::Close(_) => break,
                _ => {}
            }
            if saw_translation && saw_tts {
                break;
            }
        }
        Ok::<(), RealtimeClientError>(())
    })
    .await
    .map_err(|_| RealtimeClientError::TimedOut)?;
    receive_result?;

    socket.close(None).await?;
    if saw_translation && saw_tts {
        Ok(RealtimeAudioResult { events, playback_status })
    } else {
        Err(RealtimeClientError::IncompleteRoundtrip)
    }
}

fn build_ws_request(config: &BackendConfig) -> Result<Request<()>, RealtimeClientError> {
    let url = ws_session_url(&config.base_url)?;
    Request::builder()
        .uri(url)
        .header(HEADER_AUTH_TOKEN, &config.auth_token)
        .header(HEADER_PROTOCOL_VERSION, PROTOCOL_VERSION)
        .header(HEADER_CLIENT, &config.client_name)
        .body(())
        .map_err(|err| RealtimeClientError::InvalidRequest(err.to_string()))
}

fn ws_session_url(base_url: &str) -> Result<String, RealtimeClientError> {
    let mut url = Url::parse(base_url).map_err(|err| RealtimeClientError::InvalidUrl(err.to_string()))?;
    let scheme = match url.scheme() {
        "http" => "ws",
        "https" => "wss",
        "ws" => "ws",
        "wss" => "wss",
        other => return Err(RealtimeClientError::InvalidUrl(format!("unsupported scheme {other}"))),
    };
    url.set_scheme(scheme).map_err(|_| RealtimeClientError::InvalidUrl("failed to set websocket scheme".to_string()))?;
    url.set_path(WS_SESSION_PATH);
    url.set_query(None);
    url.set_fragment(None);
    Ok(url.to_string())
}

fn session_start_message(session_id: &str) -> Result<String, serde_json::Error> {
    serde_json::to_string(&json!({
        "protocol_version": PROTOCOL_VERSION,
        "type": "session.start",
        "session_id": session_id,
        "sequence_no": 0,
        "timestamp_ms": 0,
        "source_lang": "cmn_Hans",
        "target_lang": "eng_Latn",
        "direction": "local_to_remote",
        "stream_id": "audio_local",
        "payload": {},
        "error_code": null
    }))
}

fn mock_audio_header(session_id: &str, segment_id: &str, payload_size: usize) -> BinaryFrameHeader {
    BinaryFrameHeader {
        protocol_version: PROTOCOL_VERSION.to_string(),
        message_type: MessageType::AudioFrame,
        session_id: session_id.to_string(),
        stream_id: StreamId::AudioLocal,
        direction: Direction::LocalToRemote,
        segment_id: segment_id.to_string(),
        sequence_no: 1,
        timestamp_ms: 0,
        source_lang: Some("cmn_Hans".to_string()),
        target_lang: Some("eng_Latn".to_string()),
        sample_rate: 16_000,
        channels: 1,
        sample_format: SampleFormat::PcmS16le,
        duration_ms: 1_000,
        payload_size: payload_size as u64,
        is_final: Some(true),
    }
}

fn mock_captured_audio_frame(session_id: &str) -> CapturedAudioFrame {
    let segment_id = format!("seg_{}", Uuid::new_v4().simple());
    let payload = mock_pcm_payload();
    CapturedAudioFrame {
        header: mock_audio_header(session_id, &segment_id, payload.len()),
        payload,
    }
}

fn mock_pcm_payload() -> Vec<u8> {
    let sample = 6_000_i16.to_le_bytes();
    let mut payload = Vec::with_capacity(16_000 * 2);
    for _ in 0..16_000 {
        payload.extend_from_slice(&sample);
    }
    payload
}

fn text_to_event(text: &str) -> Result<RealtimeEvent, serde_json::Error> {
    let message: BaseMessage = serde_json::from_str(text)?;
    let kind = match message.message_type.as_str() {
        "status.update" => RealtimeEventKind::Session,
        "asr.partial" | "asr.final" => RealtimeEventKind::Transcript,
        "translate.result" => RealtimeEventKind::Translation,
        "error" => RealtimeEventKind::Error,
        _ => RealtimeEventKind::Backend,
    };
    Ok(RealtimeEvent {
        kind,
        event_name: message.message_type.clone(),
        payload: event_payload(&message),
    })
}

fn event_payload(message: &BaseMessage) -> Value {
    let mut payload = json!({
        "protocol_version": message.protocol_version,
        "type": message.message_type,
        "session_id": message.session_id,
        "stream_id": message.stream_id,
        "direction": message.direction,
        "segment_id": message.segment_id,
        "sequence_no": message.sequence_no,
        "timestamp_ms": message.timestamp_ms,
        "source_lang": message.source_lang,
        "target_lang": message.target_lang,
        "is_final": message.is_final,
        "latency_ms": message.latency_ms,
        "error_code": message.error_code,
        "data": message.payload,
    });
    if let Some(text) = message.payload.get("text").and_then(Value::as_str) {
        payload["text"] = Value::String(text.to_string());
    }
    if let Some(session_state) = message.payload.get("session_state") {
        payload["session_state"] = session_state.clone();
    }
    if let Some(backend_state) = message.payload.get("backend_state") {
        payload["backend_status"] = backend_state.clone();
    }
    payload
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derives_ws_session_url_from_http_base_url() {
        assert_eq!(ws_session_url("http://127.0.0.1:8765").unwrap(), "ws://127.0.0.1:8765/ws/session");
        assert_eq!(ws_session_url("https://localhost:8765/api").unwrap(), "wss://localhost:8765/ws/session");
    }

    #[test]
    fn builds_binary_audio_frame_without_base64_or_http_payload() {
        let payload = mock_pcm_payload();
        let frame = encode_binary_frame(&mock_audio_header("ses_test", "seg_test", payload.len()), &payload).unwrap();
        let decoded = decode_binary_frame(&frame).unwrap();
        assert_eq!(decoded.header.message_type, MessageType::AudioFrame);
        assert_eq!(decoded.payload.len(), 32_000);
    }

    #[test]
    fn maps_text_protocol_messages_to_ui_events() {
        let raw = serde_json::to_string(&json!({
            "protocol_version": PROTOCOL_VERSION,
            "type": "translate.result",
            "session_id": "ses_test",
            "stream_id": "audio_local",
            "direction": "local_to_remote",
            "segment_id": "seg_test",
            "sequence_no": 3,
            "timestamp_ms": 1,
            "source_lang": "cmn_Hans",
            "target_lang": "eng_Latn",
            "is_final": true,
            "latency_ms": 12,
            "payload": {"text": "hello"},
            "error_code": null
        }))
        .unwrap();
        let event = text_to_event(&raw).unwrap();
        assert_eq!(event.kind, RealtimeEventKind::Translation);
        assert_eq!(event.event_name, "translate.result");
        assert_eq!(event.payload["segment_id"], "seg_test");
        assert_eq!(event.payload["text"], "hello");
    }
}
