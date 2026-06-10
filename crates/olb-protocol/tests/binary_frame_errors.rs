use olb_protocol::{
    decode_binary_frame, BinaryFrameDecodeOptions, BinaryFrameError, BinaryFrameHeader, Direction, MessageType, SampleFormat, StreamId,
    PROTOCOL_VERSION,
};

fn valid_header(payload_size: u64) -> BinaryFrameHeader {
    BinaryFrameHeader {
        protocol_version: PROTOCOL_VERSION.to_string(),
        message_type: MessageType::AudioFrame,
        session_id: "ses_protocol_test".to_string(),
        stream_id: StreamId::AudioLocal,
        direction: Direction::LocalToRemote,
        segment_id: "seg_protocol_test".to_string(),
        sequence_no: 1,
        timestamp_ms: 1_700_000_000_000,
        source_lang: None,
        target_lang: None,
        sample_rate: 16_000,
        channels: 1,
        sample_format: SampleFormat::PcmS16le,
        duration_ms: 20,
        payload_size,
        is_final: None,
    }
}

fn raw_frame(header_json: &str, payload: &[u8]) -> Vec<u8> {
    let mut frame = Vec::new();
    frame.extend_from_slice(b"OLB1");
    frame.extend_from_slice(&(header_json.len() as u32).to_le_bytes());
    frame.extend_from_slice(header_json.as_bytes());
    frame.extend_from_slice(payload);
    frame
}

#[test]
fn maps_bad_magic_to_invalid_magic() {
    let err = decode_binary_frame(b"OLB2\0\0\0\0").unwrap_err();
    assert_eq!(err, BinaryFrameError::InvalidMagic);
}

#[test]
fn maps_truncated_header_to_header_truncated() {
    let mut frame = Vec::from(b"OLB1" as &[u8]);
    frame.extend_from_slice(&8_u32.to_le_bytes());
    frame.extend_from_slice(b"{}");
    let err = decode_binary_frame(&frame).unwrap_err();
    assert_eq!(err, BinaryFrameError::HeaderTruncated);
}

#[test]
fn maps_oversized_header_to_header_too_large() {
    let mut frame = Vec::from(b"OLB1" as &[u8]);
    frame.extend_from_slice(&2_u32.to_le_bytes());
    frame.extend_from_slice(b"{}");
    let err = olb_protocol::binary_frame::decode_binary_frame_with_options(
        &frame,
        BinaryFrameDecodeOptions {
            max_header_len: 1,
            validate_protocol_version: true,
        },
    )
    .unwrap_err();
    assert_eq!(err, BinaryFrameError::HeaderTooLarge { actual: 2, limit: 1 });
}

#[test]
fn maps_payload_size_mismatch() {
    let header = serde_json::to_string(&valid_header(3)).unwrap();
    let err = decode_binary_frame(&raw_frame(&header, &[0, 1])).unwrap_err();
    assert_eq!(err, BinaryFrameError::PayloadSizeMismatch { expected: 3, actual: 2 });
}

#[test]
fn maps_protocol_version_mismatch() {
    let mut header = valid_header(2);
    header.protocol_version = "9.9".to_string();
    let header = serde_json::to_string(&header).unwrap();
    let err = decode_binary_frame(&raw_frame(&header, &[0, 1])).unwrap_err();
    assert_eq!(
        err,
        BinaryFrameError::ProtocolVersionMismatch {
            expected: PROTOCOL_VERSION.to_string(),
            actual: "9.9".to_string(),
        }
    );
}

#[test]
fn maps_missing_session_id() {
    let mut header = valid_header(2);
    header.session_id.clear();
    let header = serde_json::to_string(&header).unwrap();
    let err = decode_binary_frame(&raw_frame(&header, &[0, 1])).unwrap_err();
    assert_eq!(err, BinaryFrameError::EmptyRequiredField("session_id"));
}

#[test]
fn maps_invalid_binary_message_type() {
    let mut header = valid_header(2);
    header.message_type = MessageType::StatusUpdate;
    let header = serde_json::to_string(&header).unwrap();
    let err = decode_binary_frame(&raw_frame(&header, &[0, 1])).unwrap_err();
    assert_eq!(err, BinaryFrameError::InvalidBinaryMessageType);
}
