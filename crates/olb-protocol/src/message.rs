use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::PROTOCOL_VERSION;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StreamId {
    AudioLocal,
    AudioRemote,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Direction {
    LocalToRemote,
    RemoteToLocal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SampleFormat {
    PcmS16le,
    PcmF32le,
    Wav,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SegmentState {
    Created,
    SpeechStarted,
    SpeechEnded,
    AsrPartial,
    AsrFinal,
    Translated,
    TtsGenerated,
    Played,
    Failed,
    Dropped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MessageType {
    #[serde(rename = "session.start")]
    SessionStart,
    #[serde(rename = "session.pause")]
    SessionPause,
    #[serde(rename = "session.resume")]
    SessionResume,
    #[serde(rename = "session.stop")]
    SessionStop,
    #[serde(rename = "config.update")]
    ConfigUpdate,
    #[serde(rename = "audio.frame")]
    AudioFrame,
    #[serde(rename = "asr.partial")]
    AsrPartial,
    #[serde(rename = "asr.final")]
    AsrFinal,
    #[serde(rename = "translate.result")]
    TranslateResult,
    #[serde(rename = "tts.audio")]
    TtsAudio,
    #[serde(rename = "status.update")]
    StatusUpdate,
    #[serde(rename = "error")]
    Error,
}

impl MessageType {
    pub fn is_binary_payload_type(self) -> bool {
        matches!(self, Self::AudioFrame | Self::TtsAudio)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Envelope<T> {
    pub success: bool,
    pub code: String,
    pub message: String,
    pub data: Option<T>,
    pub request_id: String,
    pub protocol_version: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BaseMessage {
    pub protocol_version: String,
    #[serde(rename = "type")]
    pub message_type: String,
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
    pub payload: Map<String, Value>,
    pub error_code: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AudioFrameHeader {
    pub protocol_version: String,
    #[serde(rename = "type")]
    pub message_type: String,
    pub session_id: String,
    pub stream_id: StreamId,
    pub direction: Direction,
    pub segment_id: String,
    pub sequence_no: u64,
    pub timestamp_ms: u64,
    pub sample_rate: u32,
    pub channels: u16,
    pub sample_format: SampleFormat,
    pub payload_size: usize,
}

impl AudioFrameHeader {
    pub fn new_audio_frame(
        session_id: impl Into<String>,
        segment_id: impl Into<String>,
        sequence_no: u64,
        payload_size: usize,
    ) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            message_type: "audio.frame".to_string(),
            session_id: session_id.into(),
            stream_id: StreamId::AudioLocal,
            direction: Direction::LocalToRemote,
            segment_id: segment_id.into(),
            sequence_no,
            timestamp_ms: 0,
            sample_rate: 16_000,
            channels: 1,
            sample_format: SampleFormat::PcmS16le,
            payload_size,
        }
    }
}
