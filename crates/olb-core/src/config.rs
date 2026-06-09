use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoreConfig {
    pub profile: String,
    pub backend: BackendConfig,
    pub privacy: PrivacyConfig,
    pub config_dir: PathBuf,
    pub log_dir: PathBuf,
    pub runtime_dir: PathBuf,
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            profile: "default".to_string(),
            backend: BackendConfig::default(),
            privacy: PrivacyConfig::default(),
            config_dir: PathBuf::from("./data/config"),
            log_dir: PathBuf::from("./data/logs"),
            runtime_dir: PathBuf::from("./data/runtime"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BackendConfig {
    pub base_url: String,
    pub auth_token: String,
    pub client_name: String,
}

impl Default for BackendConfig {
    fn default() -> Self {
        Self {
            base_url: "http://127.0.0.1:8765".to_string(),
            auth_token: "dev-token".to_string(),
            client_name: "rust-core".to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrivacyConfig {
    pub save_recording: bool,
    pub save_transcript: bool,
    pub save_translation: bool,
}

impl Default for PrivacyConfig {
    fn default() -> Self {
        Self {
            save_recording: false,
            save_transcript: false,
            save_translation: false,
        }
    }
}
