use reqwest::header::{HeaderMap, HeaderValue, CONTENT_TYPE};
use reqwest::{Client, Method};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use url::Url;

use crate::config::BackendConfig;
use olb_protocol::PROTOCOL_VERSION;

const HEADER_PROTOCOL_VERSION: &str = "X-OLB-Protocol-Version";
const HEADER_CLIENT: &str = "X-OLB-Client";
const HEADER_AUTH_TOKEN: &str = "X-OLB-Auth-Token";

#[derive(Debug, Clone)]
pub struct ModelServiceClient {
    http: Client,
    base_url: Url,
    headers: HeaderMap,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ServiceEnvelope<T = Value> {
    pub success: bool,
    pub code: String,
    pub message: String,
    pub data: Option<T>,
    pub request_id: Option<String>,
    pub protocol_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ModelLoadRequest {
    pub providers: Vec<String>,
    pub config: Value,
}

#[derive(Debug, thiserror::Error)]
pub enum ModelServiceError {
    #[error("invalid backend base url: {0}")]
    InvalidBaseUrl(#[from] url::ParseError),
    #[error("invalid request header value: {0}")]
    InvalidHeaderValue(#[from] reqwest::header::InvalidHeaderValue),
    #[error("request failed: {0}")]
    Request(#[from] reqwest::Error),
}

impl ModelServiceClient {
    pub fn new(config: &BackendConfig) -> Result<Self, ModelServiceError> {
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers.insert(HEADER_PROTOCOL_VERSION, HeaderValue::from_static(PROTOCOL_VERSION));
        headers.insert(HEADER_CLIENT, HeaderValue::from_str(&config.client_name)?);
        headers.insert(HEADER_AUTH_TOKEN, HeaderValue::from_str(&config.auth_token)?);
        Ok(Self {
            http: Client::new(),
            base_url: Url::parse(&config.base_url)?,
            headers,
        })
    }

    pub async fn health(&self) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        self.get("health").await
    }

    pub async fn models(&self) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        self.get("models").await
    }

    pub async fn voices(&self) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        self.get("voices").await
    }

    pub async fn load_model(&self, request: &ModelLoadRequest) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        self.request(Method::POST, "models/load", Some(serde_json::to_value(request).expect("model load request serializes"))).await
    }

    async fn get(&self, path: &str) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        self.request(Method::GET, path, None).await
    }

    async fn request(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<ServiceEnvelope<Value>, ModelServiceError> {
        let url = self.base_url.join(path).expect("relative API path is valid");
        let mut req = self
            .http
            .request(method, url)
            .headers(self.headers.clone());
        if let Some(body) = body {
            req = req.json(&body);
        }
        Ok(req.send().await?.error_for_status()?.json().await?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn constructs_required_headers_for_local_service() {
        let cfg = BackendConfig {
            auth_token: "local-token".to_string(),
            ..BackendConfig::default()
        };
        let client = ModelServiceClient::new(&cfg).unwrap();
        assert_eq!(client.base_url.as_str(), "http://127.0.0.1:8765/");
        assert_eq!(client.headers[HEADER_PROTOCOL_VERSION], HeaderValue::from_static("1.0"));
        assert_eq!(client.headers[HEADER_CLIENT], HeaderValue::from_static("rust-core"));
        assert_eq!(client.headers[HEADER_AUTH_TOKEN], HeaderValue::from_static("local-token"));
    }

    #[test]
    fn model_load_request_matches_python_schema() {
        let request = ModelLoadRequest {
            providers: vec!["vad".to_string(), "asr".to_string()],
            config: serde_json::json!({"mode": "mock"}),
        };
        let value = serde_json::to_value(request).unwrap();
        assert_eq!(value["providers"], serde_json::json!(["vad", "asr"]));
        assert_eq!(value["config"], serde_json::json!({"mode": "mock"}));
    }
}
