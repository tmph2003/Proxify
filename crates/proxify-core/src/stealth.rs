use crate::proxy::{Ipv4PreferredDnsResolver, HTTP2_MAX_HEADER_LIST_SIZE};
use parking_lot::{Mutex, RwLock};
use rand::Rng;
use reqwest::{header, Client};
use std::collections::HashMap;
use std::sync::{Arc, LazyLock};
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;
use tracing::{error, info, warn};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitState {
    Closed,
    Open,
    HalfOpen,
}

impl CircuitState {
    pub fn as_str(&self) -> &'static str {
        match self {
            CircuitState::Closed => "CLOSED",
            CircuitState::Open => "OPEN",
            CircuitState::HalfOpen => "HALF_OPEN",
        }
    }
}

struct CircuitBreakerInner {
    state: CircuitState,
    failures: u32,
    failure_threshold: u32,
    open_until: Instant,
    cooldown_min: u64,
    cooldown_max: u64,
}

pub struct CrawlCircuitBreaker {
    inner: Mutex<CircuitBreakerInner>,
}

impl CrawlCircuitBreaker {
    pub fn new(failure_threshold: u32, cooldown_min: u64, cooldown_max: u64) -> Self {
        Self {
            inner: Mutex::new(CircuitBreakerInner {
                state: CircuitState::Closed,
                failures: 0,
                failure_threshold,
                open_until: Instant::now(),
                cooldown_min,
                cooldown_max,
            }),
        }
    }

    pub fn allow_request(&self) -> bool {
        let mut inner = self.inner.lock();
        match inner.state {
            CircuitState::Closed => true,
            CircuitState::Open => {
                if Instant::now() >= inner.open_until {
                    info!("[CircuitBreaker] Cooldown expired. Transitioning OPEN -> HALF_OPEN (Probing).");
                    inner.state = CircuitState::HalfOpen;
                    true
                } else {
                    false
                }
            }
            CircuitState::HalfOpen => true,
        }
    }

    pub fn record_success(&self) {
        let mut inner = self.inner.lock();
        if inner.state == CircuitState::HalfOpen {
            info!("[CircuitBreaker] Probe succeeded! Transitioning HALF_OPEN -> CLOSED.");
            inner.state = CircuitState::Closed;
            inner.failures = 0;
        } else if inner.state == CircuitState::Closed && inner.failures > 0 {
            inner.failures = 0;
        }
    }

    pub fn record_failure(&self, reason: &str) {
        let mut inner = self.inner.lock();
        inner.failures += 1;
        warn!(
            "[CircuitBreaker] Recorded failure ({}/{}): {}",
            inner.failures, inner.failure_threshold, reason
        );
        if inner.state == CircuitState::HalfOpen || inner.failures >= inner.failure_threshold {
            let mut rng = rand::thread_rng();
            let cooldown = rng.gen_range(inner.cooldown_min..=inner.cooldown_max);
            inner.open_until = Instant::now() + Duration::from_secs(cooldown);
            let prev = inner.state.as_str();
            inner.state = CircuitState::Open;
            error!(
                "[CircuitBreaker] TRIPPED! Transitioning {} -> OPEN. Sleeping for {:.1} minutes.",
                prev,
                cooldown as f64 / 60.0
            );
        }
    }

    pub fn state(&self) -> CircuitState {
        self.inner.lock().state
    }
}

pub struct StealthSessionManager {
    client: Client,
    semaphore: Arc<Semaphore>,
    pub circuit_breaker: Arc<CrawlCircuitBreaker>,
}

static CUSTOM_SOFT_BLOCK_SIGNATURES: LazyLock<RwLock<Vec<String>>> =
    LazyLock::new(|| RwLock::new(Vec::new()));

const CORE_SOFT_BLOCK_SIGNATURES: &[&str] = &[
    "You\u{2019}re Temporarily Blocked",
    "Temporarily Blocked",
    "security check",
];

pub fn register_soft_block_signature(signature: &str) {
    let clean = signature.trim();
    if !clean.is_empty() {
        let mut list = CUSTOM_SOFT_BLOCK_SIGNATURES.write();
        if !list.iter().any(|s| s == clean) {
            list.push(clean.to_string());
        }
    }
}

impl StealthSessionManager {
    pub fn new(max_concurrency: usize, proxy_url: Option<&str>) -> Self {
        let mut builder = Client::builder()
            .dns_resolver(Arc::new(Ipv4PreferredDnsResolver))
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(30))
            .pool_idle_timeout(Duration::from_secs(30))
            .pool_max_idle_per_host(10)
            .http2_adaptive_window(true)
            .http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)
            .danger_accept_invalid_certs(true);

        if let Some(p) = proxy_url {
            if !p.is_empty() {
                if let Ok(proxy) = reqwest::Proxy::all(p) {
                    builder = builder.proxy(proxy);
                }
            }
        }

        let client = builder.build().unwrap_or_else(|_| Client::new());

        Self {
            client,
            semaphore: Arc::new(Semaphore::new(max_concurrency)),
            circuit_breaker: Arc::new(CrawlCircuitBreaker::new(3, 1800, 3600)),
        }
    }

    pub fn sanitize_and_match_headers(raw_headers: &HashMap<String, String>) -> header::HeaderMap {
        let mut clean = header::HeaderMap::new();
        let mut user_agent = String::new();

        for (k, v) in raw_headers {
            let k_lower = k.to_lowercase();
            if k_lower == "user-agent" {
                user_agent = v.clone();
            }
            if matches!(
                k_lower.as_str(),
                "host" | "content-length" | "connection" | "accept-encoding"
            ) {
                continue;
            }
            if let (Ok(name), Ok(val)) = (
                header::HeaderName::from_bytes(k_lower.as_bytes()),
                header::HeaderValue::from_str(v),
            ) {
                clean.insert(name, val);
            }
        }

        let ua_lower = user_agent.to_lowercase();
        let platform = if ua_lower.contains("macintosh") || ua_lower.contains("mac os x") {
            "\"macOS\""
        } else if ua_lower.contains("windows") {
            "\"Windows\""
        } else if ua_lower.contains("android") {
            "\"Android\""
        } else if ua_lower.contains("iphone") || ua_lower.contains("ipad") {
            "\"iOS\""
        } else if ua_lower.contains("linux") {
            "\"Linux\""
        } else {
            ""
        };

        if !platform.is_empty() {
            if let Ok(val) = header::HeaderValue::from_str(platform) {
                clean.insert("sec-ch-ua-platform", val);
            }
        }

        if !clean.contains_key("sec-fetch-site") {
            clean.insert(
                "sec-fetch-site",
                header::HeaderValue::from_static("same-origin"),
            );
            clean.insert("sec-fetch-mode", header::HeaderValue::from_static("cors"));
            clean.insert("sec-fetch-dest", header::HeaderValue::from_static("empty"));
        }

        clean
    }

    pub fn register_soft_block_signature(signature: &str) {
        register_soft_block_signature(signature);
    }

    pub fn is_soft_blocked(status: u16, body: &str) -> Option<String> {
        if status == 429 || status == 403 || status == 401 {
            return Some(format!("HTTP Status {}", status));
        }
        if body.is_empty() {
            return None;
        }
        let check_chunk = if body.len() > 2000 {
            let end = body
                .char_indices()
                .take_while(|(idx, _)| *idx <= 2000)
                .last()
                .map(|(idx, _)| idx)
                .unwrap_or(0);
            &body[..end]
        } else {
            body
        };
        for sig in CORE_SOFT_BLOCK_SIGNATURES {
            if check_chunk.contains(sig) {
                return Some(format!("Soft-Block Signature matched: '{}'", sig));
            }
        }
        let custom = CUSTOM_SOFT_BLOCK_SIGNATURES.read();
        for sig in custom.iter() {
            if check_chunk.contains(sig.as_str()) {
                return Some(format!("Soft-Block Signature matched: '{}'", sig));
            }
        }
        None
    }

    pub async fn post_graphql(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        form_data: &HashMap<String, String>,
        max_retries: u32,
    ) -> Option<String> {
        if !self.circuit_breaker.allow_request() {
            warn!("[StealthEngine] Request rejected: CircuitBreaker is OPEN.");
            return None;
        }

        let clean_headers = Self::sanitize_and_match_headers(headers);
        let base_delay = 2.0_f64;

        for attempt in 0..max_retries {
            let _permit = self.semaphore.acquire().await.ok()?;

            if attempt > 0 {
                let sleep_ms = {
                    let mut rng = rand::thread_rng();
                    let jitter: f64 = rng.gen_range(0.8..1.5);
                    (base_delay * 2.0_f64.powi(attempt as i32) * jitter * 1000.0) as u64
                };
                info!(
                    "[StealthEngine] Backoff retry {}/{}, waiting {:.2}s...",
                    attempt + 1,
                    max_retries,
                    sleep_ms as f64 / 1000.0
                );
                tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
            } else {
                let micro_delay = {
                    let mut rng = rand::thread_rng();
                    rng.gen_range(800..2200)
                };
                tokio::time::sleep(Duration::from_millis(micro_delay)).await;
            }

            let resp = self
                .client
                .post(url)
                .headers(clean_headers.clone())
                .form(form_data)
                .send()
                .await;

            match resp {
                Ok(r) => {
                    let status = r.status().as_u16();
                    let text = r.text().await.unwrap_or_default();
                    if let Some(block_reason) = Self::is_soft_blocked(status, &text) {
                        self.circuit_breaker.record_failure(&block_reason);
                        if !self.circuit_breaker.allow_request() {
                            return None;
                        }
                        continue;
                    }
                    if status == 200 {
                        self.circuit_breaker.record_success();
                        return Some(text);
                    } else {
                        warn!(
                            "[StealthEngine] Unexpected HTTP Status {}: {}",
                            status,
                            &text[..text.len().min(200)]
                        );
                    }
                }
                Err(e) => {
                    error!(
                        "[StealthEngine] Network error on attempt {}: {}",
                        attempt + 1,
                        e
                    );
                }
            }
        }

        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_core_soft_block_detection() {
        assert!(StealthSessionManager::is_soft_blocked(429, "").is_some());
        assert!(StealthSessionManager::is_soft_blocked(403, "").is_some());
        assert!(
            StealthSessionManager::is_soft_blocked(200, "Please complete the security check")
                .is_some()
        );
        assert!(
            StealthSessionManager::is_soft_blocked(200, "{\"data\": {\"user\": 123}}").is_none()
        );
    }

    #[test]
    fn test_custom_soft_block_signature_registration() {
        StealthSessionManager::register_soft_block_signature("\"error\":1357001");
        StealthSessionManager::register_soft_block_signature("\"is_checkpoint\":true");

        let res1 = StealthSessionManager::is_soft_blocked(
            200,
            "{\"error\":1357001, \"message\":\"checkpoint\"}",
        );
        assert!(res1.is_some());
        assert!(res1.unwrap().contains("1357001"));

        let res2 = StealthSessionManager::is_soft_blocked(200, "{\"is_checkpoint\":true}");
        assert!(res2.is_some());

        let res_ok = StealthSessionManager::is_soft_blocked(200, "{\"status\":\"ok\"}");
        assert!(res_ok.is_none());
    }
}
