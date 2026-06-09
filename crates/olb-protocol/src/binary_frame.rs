use serde::{Deserialize, Serialize};

use crate::message::{Direction, MessageType, SampleFormat, StreamId};
use crate::{DEFAULT_MAX_BINARY_HEADER_LEN, PROTOCOL_VERSION};

pub const OLB_BINARY_MAGIC: [u8; 4] = *b"OLB1";
const PREFIX_LEN: usize = 8;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum BinaryFrameError {
    #[error("frame too short")]
    TooShort,
    #[error("binary frame magic does not match OLB1")]
    InvalidMagic,
    #[error("header truncated")]
    HeaderTruncated,
    #[error("header length {actual} exceeds limit {limit}")]
    HeaderTooLarge { actual: usize, limit: usize },
    #[error("json error: {0}")]
    Json(String),
    #[error("payload_size mismatch: expected {expected}, actual {actual}")]
    PayloadSizeMismatch { expected: u64, actual: u64 },
    #[error("protocol version mismatch: expected {expected}, actual {actual}")]
    ProtocolVersionMismatch { expected: String, actual: String },
    #[error("required field {0} is empty")]
    EmptyRequiredField(&'static str),
    #[error("message type is not valid for binary payload")]
    InvalidBinaryMessageType,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BinaryFrameHeader {
    pub protocol_version: String,
    #[serde(rename = "type")]
    pub message_type: MessageType,
    pub session_id: String,
    pub stream_id: StreamId,
    pub direction: Direction,
    pub segment_id: String,
    pub sequence_no: u64,
    pub timestamp_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_lang: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_lang: Option<String>,
    pub sample_rate: u32,
    pub channels: u16,
    pub sample_format: SampleFormat,
    pub duration_ms: u32,
    pub payload_size: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_final: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BinaryFrame {
    pub header: BinaryFrameHeader,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BinaryFrameDecodeOptions {
    pub max_header_len: usize,
    pub validate_protocol_version: bool,
}

impl Default for BinaryFrameDecodeOptions {
    fn default() -> Self {
        Self {
            max_header_len: DEFAULT_MAX_BINARY_HEADER_LEN,
            validate_protocol_version: true,
        }
    }
}

pub fn encode_binary_frame(header: &BinaryFrameHeader, payload: &[u8]) -> Result<Vec<u8>, BinaryFrameError> {
    validate_header(header, payload.len() as u64)?;
    let header = serde_json::to_vec(header).map_err(|err| BinaryFrameError::Json(err.to_string()))?;
    let header_len = u32::try_from(header.len()).map_err(|_| BinaryFrameError::HeaderTooLarge {
        actual: header.len(),
        limit: u32::MAX as usize,
    })?;
    let mut out = Vec::with_capacity(PREFIX_LEN + header.len() + payload.len());
    out.extend_from_slice(&OLB_BINARY_MAGIC);
    out.extend_from_slice(&header_len.to_le_bytes());
    out.extend_from_slice(&header);
    out.extend_from_slice(payload);
    Ok(out)
}

pub fn decode_binary_frame(frame: &[u8]) -> Result<BinaryFrame, BinaryFrameError> {
    decode_binary_frame_with_options(frame, BinaryFrameDecodeOptions::default())
}

pub fn decode_binary_frame_with_options(
    frame: &[u8],
    options: BinaryFrameDecodeOptions,
) -> Result<BinaryFrame, BinaryFrameError> {
    if frame.len() < PREFIX_LEN {
        return Err(BinaryFrameError::TooShort);
    }
    if frame[..4] != OLB_BINARY_MAGIC {
        return Err(BinaryFrameError::InvalidMagic);
    }
    let header_len = u32::from_le_bytes(frame[4..8].try_into().expect("slice length checked")) as usize;
    if header_len > options.max_header_len {
        return Err(BinaryFrameError::HeaderTooLarge {
            actual: header_len,
            limit: options.max_header_len,
        });
    }
    let header_end = PREFIX_LEN + header_len;
    if frame.len() < header_end {
        return Err(BinaryFrameError::HeaderTruncated);
    }
    let header: BinaryFrameHeader = serde_json::from_slice(&frame[PREFIX_LEN..header_end])
        .map_err(|err| BinaryFrameError::Json(err.to_string()))?;
    if options.validate_protocol_version && header.protocol_version != PROTOCOL_VERSION {
        return Err(BinaryFrameError::ProtocolVersionMismatch {
            expected: PROTOCOL_VERSION.to_string(),
            actual: header.protocol_version,
        });
    }
    let payload = frame[header_end..].to_vec();
    validate_header(&header, payload.len() as u64)?;
    Ok(BinaryFrame { header, payload })
}

fn validate_header(header: &BinaryFrameHeader, actual_payload_size: u64) -> Result<(), BinaryFrameError> {
    if !header.message_type.is_binary_payload_type() {
        return Err(BinaryFrameError::InvalidBinaryMessageType);
    }
    if header.session_id.is_empty() {
        return Err(BinaryFrameError::EmptyRequiredField("session_id"));
    }
    if header.segment_id.is_empty() {
        return Err(BinaryFrameError::EmptyRequiredField("segment_id"));
    }
    if header.payload_size != actual_payload_size {
        return Err(BinaryFrameError::PayloadSizeMismatch {
            expected: header.payload_size,
            actual: actual_payload_size,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_header(payload_size: u64) -> BinaryFrameHeader {
        BinaryFrameHeader {
            protocol_version: PROTOCOL_VERSION.to_string(),
            message_type: MessageType::AudioFrame,
            session_id: "ses_01HZXABC".to_string(),
            stream_id: StreamId::AudioLocal,
            direction: Direction::LocalToRemote,
            segment_id: "seg_000001".to_string(),
            sequence_no: 12,
            timestamp_ms: 1_780_000_000_000,
            source_lang: Some("cmn_Hans".to_string()),
            target_lang: Some("eng_Latn".to_string()),
            sample_rate: 16_000,
            channels: 1,
            sample_format: SampleFormat::PcmS16le,
            duration_ms: 20,
            payload_size,
            is_final: Some(false),
        }
    }

    #[test]
    fn encodes_magic_little_endian_header_and_payload() {
        let payload = [0_u8, 1, 2, 3];
        let header = sample_header(payload.len() as u64);
        let encoded = encode_binary_frame(&header, &payload).unwrap();
        assert_eq!(&encoded[..4], b"OLB1");
        let header_len = u32::from_le_bytes(encoded[4..8].try_into().unwrap()) as usize;
        let header_json: serde_json::Value = serde_json::from_slice(&encoded[8..8 + header_len]).unwrap();
        assert_eq!(header_json["protocol_version"], "1.0");
        assert_eq!(header_json["type"], "audio.frame");
        assert_eq!(&encoded[8 + header_len..], payload);
    }

    #[test]
    fn roundtrips_binary_frame() {
        let payload = [0_u8, 1, 2, 3];
        let header = sample_header(payload.len() as u64);
        let encoded = encode_binary_frame(&header, &payload).unwrap();
        let decoded = decode_binary_frame(&encoded).unwrap();
        assert_eq!(decoded.header, header);
        assert_eq!(decoded.payload, payload);
    }

    #[test]
    fn rejects_bad_magic() {
        let err = decode_binary_frame(b"OLB2\0\0\0\0").unwrap_err();
        assert_eq!(err, BinaryFrameError::InvalidMagic);
    }

    #[test]
    fn rejects_payload_size_mismatch() {
        let header = sample_header(99);
        let err = encode_binary_frame(&header, &[1, 2, 3]).unwrap_err();
        assert_eq!(err, BinaryFrameError::PayloadSizeMismatch { expected: 99, actual: 3 });
    }
}
