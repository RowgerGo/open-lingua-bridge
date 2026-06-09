pub mod binary_frame;
pub mod message;

pub use binary_frame::{decode_binary_frame, encode_binary_frame, BinaryFrame, BinaryFrameDecodeOptions, BinaryFrameError, BinaryFrameHeader, OLB_BINARY_MAGIC};
pub use message::{AudioFrameHeader, BaseMessage, Direction, Envelope, MessageType, SampleFormat, SegmentState, StreamId};

pub const PROTOCOL_VERSION: &str = "1.0";
pub const CLIENT_NAME: &str = "rust-core";
pub const WS_SESSION_PATH: &str = "/ws/session";
pub const DEFAULT_MAX_BINARY_HEADER_LEN: usize = 64 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    Ok,
    InvalidRequest,
    Unauthorized,
    ProtocolVersionMismatch,
    BackendUnreachable,
    BackendNotReady,
    AudioDeviceUnavailable,
    AudioPermissionDenied,
    AudioCaptureFailed,
    AudioResampleFailed,
    ModelFileMissing,
    ModelLoadFailed,
    LanguageChainIncomplete,
    AsrRequestFailed,
    TranslateRequestFailed,
    TtsRequestFailed,
    PlaybackQueueOverloaded,
    SessionNotFound,
    SessionStateInvalid,
    InternalError,
}
