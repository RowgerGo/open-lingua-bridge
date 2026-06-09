use std::collections::VecDeque;
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{SampleFormat as CpalSampleFormat, StreamConfig};
use olb_protocol::{BinaryFrameHeader, Direction, MessageType, SampleFormat, StreamId, PROTOCOL_VERSION};
use serde::{Deserialize, Serialize};

pub const TARGET_SAMPLE_RATE: u32 = 16_000;
pub const TARGET_CHANNELS: u16 = 1;
pub const DEFAULT_FRAME_DURATION_MS: u32 = 20;
pub const DEFAULT_SEGMENT_FRAME_COUNT: u32 = 50;
const DEFAULT_CAPTURE_TIMEOUT: Duration = Duration::from_secs(3);
const DEFAULT_PLAYBACK_QUEUE_SAMPLES: usize = TARGET_SAMPLE_RATE as usize * 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AudioDeviceKind {
    Input,
    Output,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioDeviceFormat {
    pub channels: u16,
    pub min_sample_rate: u32,
    pub max_sample_rate: u32,
    pub sample_format: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioDeviceInfo {
    pub id: String,
    pub name: String,
    pub kind: AudioDeviceKind,
    pub is_default: bool,
    pub formats: Vec<AudioDeviceFormat>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioDevices {
    pub inputs: Vec<AudioDeviceInfo>,
    pub outputs: Vec<AudioDeviceInfo>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CaptureConfig {
    pub device_id: Option<String>,
    pub stream_id: StreamId,
    pub direction: Direction,
    pub frame_duration_ms: u32,
    pub segment_frame_count: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioRouteConfig {
    pub output_device_id: Option<String>,
    pub virtual_microphone_device_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapturedAudioFrame {
    pub header: BinaryFrameHeader,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlaybackQueueStatus {
    pub queued_samples: usize,
    pub queued_duration_ms: u32,
    pub capacity_samples: usize,
}

#[derive(Debug, thiserror::Error)]
pub enum AudioError {
    #[error("audio device unavailable: {0}")]
    DeviceUnavailable(String),
    #[error("audio permission denied or capture failed: {0}")]
    CaptureFailed(String),
    #[error("audio playback failed: {0}")]
    PlaybackFailed(String),
    #[error("audio resample failed: {0}")]
    ResampleFailed(String),
    #[error("playback queue overloaded: queued {queued_samples}, capacity {capacity_samples}")]
    PlaybackQueueOverloaded { queued_samples: usize, capacity_samples: usize },
}

#[derive(Debug)]
pub struct PlaybackQueue {
    capacity_samples: usize,
    samples: VecDeque<f32>,
}

impl PlaybackQueue {
    pub fn new(capacity_samples: usize) -> Self {
        Self {
            capacity_samples,
            samples: VecDeque::new(),
        }
    }

    pub fn push_pcm_s16le(&mut self, payload: &[u8], sample_rate: u32, channels: u16) -> Result<PlaybackQueueStatus, AudioError> {
        let mono = pcm_s16le_to_mono_f32(payload, channels)?;
        let target = resample_linear(&mono, sample_rate, TARGET_SAMPLE_RATE)?;
        if self.samples.len() + target.len() > self.capacity_samples {
            return Err(AudioError::PlaybackQueueOverloaded {
                queued_samples: self.samples.len() + target.len(),
                capacity_samples: self.capacity_samples,
            });
        }
        self.samples.extend(target);
        Ok(self.status())
    }

    pub fn drain_all(&mut self) -> Vec<f32> {
        self.samples.drain(..).collect()
    }

    pub fn status(&self) -> PlaybackQueueStatus {
        PlaybackQueueStatus {
            queued_samples: self.samples.len(),
            queued_duration_ms: duration_ms_for_samples(self.samples.len(), TARGET_SAMPLE_RATE),
            capacity_samples: self.capacity_samples,
        }
    }
}

pub fn default_capture_config(stream_id: StreamId, direction: Direction) -> CaptureConfig {
    CaptureConfig {
        device_id: None,
        stream_id,
        direction,
        frame_duration_ms: DEFAULT_FRAME_DURATION_MS,
        segment_frame_count: DEFAULT_SEGMENT_FRAME_COUNT,
    }
}

pub fn enumerate_audio_devices() -> Result<AudioDevices, AudioError> {
    let host = cpal::default_host();
    let default_input = host.default_input_device().and_then(|device| device.name().ok());
    let default_output = host.default_output_device().and_then(|device| device.name().ok());
    let inputs = host
        .input_devices()
        .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?
        .enumerate()
        .map(|(index, device)| device_info(index, device, AudioDeviceKind::Input, default_input.as_deref()))
        .collect::<Result<Vec<_>, _>>()?;
    let outputs = host
        .output_devices()
        .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?
        .enumerate()
        .map(|(index, device)| device_info(index, device, AudioDeviceKind::Output, default_output.as_deref()))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(AudioDevices { inputs, outputs })
}

pub fn capture_audio_frames(config: &CaptureConfig, session_id: &str, frame_count: usize) -> Result<Vec<CapturedAudioFrame>, AudioError> {
    let host = cpal::default_host();
    let device = select_device(&host, AudioDeviceKind::Input, config.device_id.as_deref())?;
    let supported = device
        .default_input_config()
        .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?;
    let sample_format = supported.sample_format();
    let stream_config: StreamConfig = supported.into();
    let source_sample_rate = stream_config.sample_rate.0;
    let source_channels = stream_config.channels;
    let (sender, receiver) = mpsc::channel::<Vec<f32>>();
    let error_slot = Arc::new(Mutex::new(None::<String>));
    let error_sink = Arc::clone(&error_slot);
    let err_fn = move |err: cpal::StreamError| {
        if let Ok(mut slot) = error_sink.lock() {
            *slot = Some(err.to_string());
        }
    };

    let stream = match sample_format {
        CpalSampleFormat::I16 => build_input_stream_i16(&device, &stream_config, source_channels, sender, err_fn),
        CpalSampleFormat::U16 => build_input_stream_u16(&device, &stream_config, source_channels, sender, err_fn),
        CpalSampleFormat::F32 => build_input_stream_f32(&device, &stream_config, source_channels, sender, err_fn),
        other => Err(AudioError::CaptureFailed(format!("unsupported input sample format {other:?}"))),
    }?;
    stream.play().map_err(|err| AudioError::CaptureFailed(err.to_string()))?;

    let mut scheduler = SegmentScheduler::new(config.segment_frame_count.max(1));
    let mut source_buffer = Vec::<f32>::new();
    let source_samples_per_frame = ((source_sample_rate as u64 * config.frame_duration_ms.max(1) as u64) / 1_000).max(1) as usize;
    let target_samples_per_frame = ((TARGET_SAMPLE_RATE as u64 * config.frame_duration_ms.max(1) as u64) / 1_000).max(1) as usize;
    let mut frames = Vec::with_capacity(frame_count);

    while frames.len() < frame_count {
        if let Some(err) = error_slot.lock().map_err(|err| AudioError::CaptureFailed(err.to_string()))?.take() {
            return Err(AudioError::CaptureFailed(err));
        }
        let chunk = receiver
            .recv_timeout(DEFAULT_CAPTURE_TIMEOUT)
            .map_err(|err| AudioError::CaptureFailed(format!("no audio input received: {err}")))?;
        source_buffer.extend(chunk);
        while source_buffer.len() >= source_samples_per_frame && frames.len() < frame_count {
            let chunk: Vec<f32> = source_buffer.drain(..source_samples_per_frame).collect();
            let mut target = resample_linear(&chunk, source_sample_rate, TARGET_SAMPLE_RATE)?;
            target.resize(target_samples_per_frame, 0.0);
            let payload = f32_to_pcm_s16le(&target);
            let sequence_no = scheduler.next_sequence_no();
            let segment_id = scheduler.segment_id().to_string();
            frames.push(CapturedAudioFrame {
                header: BinaryFrameHeader {
                    protocol_version: PROTOCOL_VERSION.to_string(),
                    message_type: MessageType::AudioFrame,
                    session_id: session_id.to_string(),
                    stream_id: config.stream_id,
                    direction: config.direction,
                    segment_id,
                    sequence_no,
                    timestamp_ms: timestamp_ms(),
                    source_lang: None,
                    target_lang: None,
                    sample_rate: TARGET_SAMPLE_RATE,
                    channels: TARGET_CHANNELS,
                    sample_format: SampleFormat::PcmS16le,
                    duration_ms: config.frame_duration_ms,
                    payload_size: payload.len() as u64,
                    is_final: Some(false),
                },
                payload,
            });
            scheduler.advance_frame();
        }
    }
    drop(stream);
    Ok(frames)
}

pub fn play_tts_audio(route: &AudioRouteConfig, payload: &[u8], sample_rate: u32, channels: u16) -> Result<PlaybackQueueStatus, AudioError> {
    let mut queue = PlaybackQueue::new(DEFAULT_PLAYBACK_QUEUE_SAMPLES);
    let status = queue.push_pcm_s16le(payload, sample_rate, channels)?;
    let samples = queue.drain_all();
    play_mono_f32_to_output(route.output_device_id.as_deref(), &samples, TARGET_SAMPLE_RATE)?;
    if let Some(device_id) = route.virtual_microphone_device_id.as_deref() {
        play_mono_f32_to_output(Some(device_id), &samples, TARGET_SAMPLE_RATE)?;
    }
    Ok(status)
}

fn device_info(index: usize, device: cpal::Device, kind: AudioDeviceKind, default_name: Option<&str>) -> Result<AudioDeviceInfo, AudioError> {
    let name = device.name().map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?;
    let formats = match kind {
        AudioDeviceKind::Input => device
            .supported_input_configs()
            .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?
            .map(|format| AudioDeviceFormat {
                channels: format.channels(),
                min_sample_rate: format.min_sample_rate().0,
                max_sample_rate: format.max_sample_rate().0,
                sample_format: format.sample_format().to_string(),
            })
            .collect(),
        AudioDeviceKind::Output => device
            .supported_output_configs()
            .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?
            .map(|format| AudioDeviceFormat {
                channels: format.channels(),
                min_sample_rate: format.min_sample_rate().0,
                max_sample_rate: format.max_sample_rate().0,
                sample_format: format.sample_format().to_string(),
            })
            .collect(),
    };
    Ok(AudioDeviceInfo {
        id: format!("{:?}:{index}:{name}", kind).to_lowercase(),
        is_default: default_name == Some(name.as_str()),
        name,
        kind,
        formats,
    })
}

fn select_device(host: &cpal::Host, kind: AudioDeviceKind, requested_id: Option<&str>) -> Result<cpal::Device, AudioError> {
    if let Some(id) = requested_id {
        let devices = match kind {
            AudioDeviceKind::Input => host.input_devices(),
            AudioDeviceKind::Output => host.output_devices(),
        }
        .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?;
        for (index, device) in devices.enumerate() {
            let name = device.name().map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?;
            let candidate_id = format!("{:?}:{index}:{name}", kind).to_lowercase();
            if candidate_id == id || name == id {
                return Ok(device);
            }
        }
        return Err(AudioError::DeviceUnavailable(id.to_string()));
    }
    match kind {
        AudioDeviceKind::Input => host.default_input_device(),
        AudioDeviceKind::Output => host.default_output_device(),
    }
    .ok_or_else(|| AudioError::DeviceUnavailable(format!("default {kind:?} device")))
}

fn build_input_stream_i16(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: u16,
    sender: mpsc::Sender<Vec<f32>>,
    err_fn: impl FnMut(cpal::StreamError) + Send + 'static,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_input_stream(
            config,
            move |data: &[i16], _| {
                let _ = sender.send(interleaved_i16_to_mono(data, channels));
            },
            err_fn,
            None,
        )
        .map_err(|err| AudioError::CaptureFailed(err.to_string()))
}

fn build_input_stream_u16(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: u16,
    sender: mpsc::Sender<Vec<f32>>,
    err_fn: impl FnMut(cpal::StreamError) + Send + 'static,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_input_stream(
            config,
            move |data: &[u16], _| {
                let _ = sender.send(interleaved_u16_to_mono(data, channels));
            },
            err_fn,
            None,
        )
        .map_err(|err| AudioError::CaptureFailed(err.to_string()))
}

fn build_input_stream_f32(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: u16,
    sender: mpsc::Sender<Vec<f32>>,
    err_fn: impl FnMut(cpal::StreamError) + Send + 'static,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_input_stream(
            config,
            move |data: &[f32], _| {
                let _ = sender.send(interleaved_f32_to_mono(data, channels));
            },
            err_fn,
            None,
        )
        .map_err(|err| AudioError::CaptureFailed(err.to_string()))
}

fn play_mono_f32_to_output(device_id: Option<&str>, samples: &[f32], source_rate: u32) -> Result<(), AudioError> {
    if samples.is_empty() {
        return Ok(());
    }
    let host = cpal::default_host();
    let device = select_device(&host, AudioDeviceKind::Output, device_id)?;
    let supported = device
        .default_output_config()
        .map_err(|err| AudioError::DeviceUnavailable(err.to_string()))?;
    let sample_format = supported.sample_format();
    let stream_config: StreamConfig = supported.into();
    let output_rate = stream_config.sample_rate.0;
    let channels = stream_config.channels as usize;
    let resampled = resample_linear(samples, source_rate, output_rate)?;
    let shared = Arc::new(Mutex::new((resampled, 0usize)));
    let stream = match sample_format {
        CpalSampleFormat::I16 => build_output_stream_i16(&device, &stream_config, channels, Arc::clone(&shared)),
        CpalSampleFormat::U16 => build_output_stream_u16(&device, &stream_config, channels, Arc::clone(&shared)),
        CpalSampleFormat::F32 => build_output_stream_f32(&device, &stream_config, channels, Arc::clone(&shared)),
        other => Err(AudioError::PlaybackFailed(format!("unsupported output sample format {other:?}"))),
    }?;
    stream.play().map_err(|err| AudioError::PlaybackFailed(err.to_string()))?;
    std::thread::sleep(Duration::from_millis(duration_ms_for_samples(samples.len(), source_rate) as u64 + 80));
    drop(stream);
    Ok(())
}

fn build_output_stream_i16(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: usize,
    samples: Arc<Mutex<(Vec<f32>, usize)>>,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_output_stream(
            config,
            move |data: &mut [i16], _| fill_output_i16(data, channels, &samples),
            |_| {},
            None,
        )
        .map_err(|err| AudioError::PlaybackFailed(err.to_string()))
}

fn build_output_stream_u16(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: usize,
    samples: Arc<Mutex<(Vec<f32>, usize)>>,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_output_stream(
            config,
            move |data: &mut [u16], _| fill_output_u16(data, channels, &samples),
            |_| {},
            None,
        )
        .map_err(|err| AudioError::PlaybackFailed(err.to_string()))
}

fn build_output_stream_f32(
    device: &cpal::Device,
    config: &StreamConfig,
    channels: usize,
    samples: Arc<Mutex<(Vec<f32>, usize)>>,
) -> Result<cpal::Stream, AudioError> {
    device
        .build_output_stream(
            config,
            move |data: &mut [f32], _| fill_output_f32(data, channels, &samples),
            |_| {},
            None,
        )
        .map_err(|err| AudioError::PlaybackFailed(err.to_string()))
}

fn fill_output_i16(data: &mut [i16], channels: usize, samples: &Arc<Mutex<(Vec<f32>, usize)>>) {
    fill_output(data, channels, samples, |sample| (sample.clamp(-1.0, 1.0) * i16::MAX as f32) as i16);
}

fn fill_output_u16(data: &mut [u16], channels: usize, samples: &Arc<Mutex<(Vec<f32>, usize)>>) {
    fill_output(data, channels, samples, |sample| ((sample.clamp(-1.0, 1.0) + 1.0) * 0.5 * u16::MAX as f32) as u16);
}

fn fill_output_f32(data: &mut [f32], channels: usize, samples: &Arc<Mutex<(Vec<f32>, usize)>>) {
    fill_output(data, channels, samples, |sample| sample.clamp(-1.0, 1.0));
}

fn fill_output<T: Copy>(data: &mut [T], channels: usize, samples: &Arc<Mutex<(Vec<f32>, usize)>>, convert: impl Fn(f32) -> T) {
    let Ok(mut guard) = samples.lock() else {
        return;
    };
    let (source, cursor) = &mut *guard;
    for frame in data.chunks_mut(channels.max(1)) {
        let sample = source.get(*cursor).copied().unwrap_or(0.0);
        if *cursor < source.len() {
            *cursor += 1;
        }
        for out in frame {
            *out = convert(sample);
        }
    }
}

fn interleaved_i16_to_mono(data: &[i16], channels: u16) -> Vec<f32> {
    interleaved_to_mono(data, channels, |sample| sample as f32 / i16::MAX as f32)
}

fn interleaved_u16_to_mono(data: &[u16], channels: u16) -> Vec<f32> {
    interleaved_to_mono(data, channels, |sample| (sample as f32 / u16::MAX as f32) * 2.0 - 1.0)
}

fn interleaved_f32_to_mono(data: &[f32], channels: u16) -> Vec<f32> {
    interleaved_to_mono(data, channels, |sample| sample)
}

fn interleaved_to_mono<T: Copy>(data: &[T], channels: u16, convert: impl Fn(T) -> f32) -> Vec<f32> {
    let channels = channels.max(1) as usize;
    data.chunks(channels)
        .map(|frame| frame.iter().copied().map(&convert).sum::<f32>() / frame.len().max(1) as f32)
        .collect()
}

fn pcm_s16le_to_mono_f32(payload: &[u8], channels: u16) -> Result<Vec<f32>, AudioError> {
    if payload.len() % 2 != 0 {
        return Err(AudioError::ResampleFailed("pcm_s16le payload length is not even".to_string()));
    }
    let samples = payload
        .chunks_exact(2)
        .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]))
        .collect::<Vec<_>>();
    Ok(interleaved_i16_to_mono(&samples, channels))
}

fn f32_to_pcm_s16le(samples: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(samples.len() * 2);
    for sample in samples {
        let sample = ((*sample).clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
        out.extend_from_slice(&sample.to_le_bytes());
    }
    out
}

fn resample_linear(samples: &[f32], source_rate: u32, target_rate: u32) -> Result<Vec<f32>, AudioError> {
    if source_rate == 0 || target_rate == 0 {
        return Err(AudioError::ResampleFailed("sample rate must be greater than zero".to_string()));
    }
    if samples.is_empty() || source_rate == target_rate {
        return Ok(samples.to_vec());
    }
    let target_len = ((samples.len() as u64 * target_rate as u64) / source_rate as u64).max(1) as usize;
    let ratio = source_rate as f64 / target_rate as f64;
    let mut out = Vec::with_capacity(target_len);
    for index in 0..target_len {
        let source_pos = index as f64 * ratio;
        let lower = source_pos.floor() as usize;
        let upper = (lower + 1).min(samples.len() - 1);
        let frac = (source_pos - lower as f64) as f32;
        out.push(samples[lower] * (1.0 - frac) + samples[upper] * frac);
    }
    Ok(out)
}

fn duration_ms_for_samples(samples: usize, sample_rate: u32) -> u32 {
    ((samples as u64 * 1_000) / sample_rate.max(1) as u64) as u32
}

fn timestamp_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[derive(Debug)]
struct SegmentScheduler {
    segment_index: u64,
    sequence_no: u64,
    frame_index: u32,
    frames_per_segment: u32,
}

impl SegmentScheduler {
    fn new(frames_per_segment: u32) -> Self {
        Self {
            segment_index: 1,
            sequence_no: 1,
            frame_index: 0,
            frames_per_segment,
        }
    }

    fn segment_id(&self) -> String {
        format!("seg_{:06}", self.segment_index)
    }

    fn next_sequence_no(&mut self) -> u64 {
        let current = self.sequence_no;
        self.sequence_no += 1;
        current
    }

    fn advance_frame(&mut self) {
        self.frame_index += 1;
        if self.frame_index >= self.frames_per_segment {
            self.frame_index = 0;
            self.segment_index += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_interleaved_stereo_to_mono() {
        let mono = interleaved_i16_to_mono(&[i16::MAX, 0, 0, i16::MAX], 2);
        assert_eq!(mono.len(), 2);
        assert!((mono[0] - 0.5).abs() < 0.01);
        assert!((mono[1] - 0.5).abs() < 0.01);
    }

    #[test]
    fn resamples_to_target_rate() {
        let source = vec![0.0; 480];
        let target = resample_linear(&source, 48_000, TARGET_SAMPLE_RATE).unwrap();
        assert_eq!(target.len(), 160);
    }

    #[test]
    fn scheduler_increments_sequence_and_segments() {
        let mut scheduler = SegmentScheduler::new(2);
        assert_eq!(scheduler.segment_id(), "seg_000001");
        assert_eq!(scheduler.next_sequence_no(), 1);
        scheduler.advance_frame();
        assert_eq!(scheduler.segment_id(), "seg_000001");
        assert_eq!(scheduler.next_sequence_no(), 2);
        scheduler.advance_frame();
        assert_eq!(scheduler.segment_id(), "seg_000002");
    }

    #[test]
    fn playback_queue_rejects_overflow() {
        let mut queue = PlaybackQueue::new(2);
        let payload = vec![0; 8];
        let err = queue.push_pcm_s16le(&payload, TARGET_SAMPLE_RATE, TARGET_CHANNELS).unwrap_err();
        assert!(matches!(err, AudioError::PlaybackQueueOverloaded { .. }));
    }

    #[test]
    fn playback_queue_accepts_pcm_s16le() {
        let mut queue = PlaybackQueue::new(16);
        let status = queue.push_pcm_s16le(&[0, 0, 255, 127], TARGET_SAMPLE_RATE, TARGET_CHANNELS).unwrap();
        assert_eq!(status.queued_samples, 2);
        assert_eq!(queue.drain_all().len(), 2);
    }
}
