use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::oneshot;
use tracing::{info, warn};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeJob {
    pub id: String,
    pub job_id: String,
    pub url: String,
    pub method: String,
    pub headers: HashMap<String, String>,
    pub body: Option<String>,
    pub form_data: HashMap<String, String>,
    pub target_group_url: String,
    pub client_id: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct BridgeResultPayload {
    pub id: Option<String>,
    pub job_id: Option<String>,
    pub client_id: Option<String>,
    pub ok: Option<bool>,
    pub status: Option<u16>,
    pub text: Option<String>,
    pub error: Option<String>,
    pub result: Option<Value>,
}

struct ClientSession {
    last_seen: Instant,
    user_agent: String,
    pending_jobs: VecDeque<BridgeJob>,
}

pub struct ExtensionBridge {
    clients: DashMap<String, ClientSession>,
    job_to_client: DashMap<String, String>,
    waiters: DashMap<String, oneshot::Sender<Value>>,
}

impl ExtensionBridge {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            clients: DashMap::new(),
            job_to_client: DashMap::new(),
            waiters: DashMap::new(),
        })
    }

    pub fn record_heartbeat(&self, client_id: &str, user_agent: &str) {
        let mut entry = self
            .clients
            .entry(client_id.to_string())
            .or_insert_with(|| ClientSession {
                last_seen: Instant::now(),
                user_agent: user_agent.to_string(),
                pending_jobs: VecDeque::new(),
            });
        entry.last_seen = Instant::now();
        if !user_agent.is_empty() {
            entry.user_agent = user_agent.to_string();
        }
    }

    pub fn is_connected(&self) -> bool {
        self.clients
            .iter()
            .any(|entry| entry.value().last_seen.elapsed().as_secs() <= 60)
    }

    pub fn is_client_connected(&self, client_id: &str) -> bool {
        if let Some(entry) = self.clients.get(client_id) {
            if entry.last_seen.elapsed().as_secs() <= 60 {
                return true;
            }
        }
        // Fallback to any connected client if "default" or single-user mode
        self.is_connected()
    }

    pub fn get_status(&self) -> Value {
        let connected = self.is_connected();
        let mut total_pending = 0;
        let active_clients: Vec<Value> = self
            .clients
            .iter()
            .filter(|e| e.value().last_seen.elapsed().as_secs() <= 60)
            .map(|entry| {
                total_pending += entry.value().pending_jobs.len();
                json!({
                    "client_id": entry.key(),
                    "user_agent": entry.value().user_agent,
                    "age_seconds": entry.value().last_seen.elapsed().as_secs(),
                })
            })
            .collect();

        json!({
            "connected": connected,
            "client_count": active_clients.len(),
            "clients": active_clients,
            "pending_jobs": total_pending,
        })
    }

    pub fn pop_job(&self, client_id: &str) -> Option<BridgeJob> {
        if let Some(mut session) = self.clients.get_mut(client_id) {
            if let Some(job) = session.pending_jobs.pop_front() {
                return Some(job);
            }
        }
        if client_id != "default" {
            if let Some(mut def_session) = self.clients.get_mut("default") {
                if let Some(job) = def_session.pending_jobs.pop_front() {
                    return Some(job);
                }
            }
        }
        None
    }

    pub fn submit_result(&self, payload: BridgeResultPayload) -> bool {
        let jid = payload
            .id
            .clone()
            .or_else(|| payload.job_id.clone())
            .unwrap_or_default();
        if jid.is_empty() {
            return false;
        }
        self.job_to_client.remove(&jid);

        if let Some((_, tx)) = self.waiters.remove(&jid) {
            let res_val = if let Some(r) = payload.result {
                r
            } else {
                json!({
                    "status_code": payload.status.unwrap_or(if payload.ok.unwrap_or(false) { 200 } else { 0 }),
                    "text": payload.text.unwrap_or_default(),
                    "error": payload.error,
                })
            };
            let _ = tx.send(res_val);
            true
        } else {
            false
        }
    }

    pub async fn execute_graphql(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        form_data: &HashMap<String, String>,
        timeout_secs: u64,
    ) -> Option<String> {
        self.execute_graphql_for_client("default", url, headers, form_data, timeout_secs)
            .await
    }

    pub async fn execute_graphql_for_client(
        &self,
        client_id: &str,
        url: &str,
        headers: &HashMap<String, String>,
        form_data: &HashMap<String, String>,
        timeout_secs: u64,
    ) -> Option<String> {
        if !url.contains("/api/graphql") {
            warn!(
                "[ExtensionBridge] Rejected non-GraphQL URL for safety: {}",
                url
            );
            return None;
        }
        if !self.is_client_connected(client_id) {
            return None;
        }

        let job_id = Uuid::new_v4().to_string();
        let (tx, rx) = oneshot::channel();
        self.waiters.insert(job_id.clone(), tx);

        let mut safe_headers = HashMap::new();
        let mut target_group_url = String::new();
        for (k, v) in headers {
            let k_low = k.to_lowercase();
            if k_low == "referer" && v.contains("/groups/") {
                target_group_url = v.clone();
            }
            if matches!(
                k_low.as_str(),
                "cookie"
                    | "user-agent"
                    | "host"
                    | "referer"
                    | "origin"
                    | "sec-ch-ua"
                    | "sec-ch-ua-mobile"
                    | "sec-ch-ua-platform"
                    | "accept-encoding"
                    | "connection"
            ) {
                continue;
            }
            safe_headers.insert(k.clone(), v.clone());
        }
        safe_headers
            .entry("Content-Type".to_string())
            .or_insert_with(|| "application/x-www-form-urlencoded".to_string());

        let body_urlencoded: String = form_data
            .iter()
            .map(|(k, v)| format!("{}={}", urlencoding::encode(k), urlencoding::encode(v)))
            .collect::<Vec<_>>()
            .join("&");

        let job = BridgeJob {
            id: job_id.clone(),
            job_id: job_id.clone(),
            url: url.to_string(),
            method: "POST".to_string(),
            headers: safe_headers,
            body: Some(body_urlencoded),
            form_data: form_data.clone(),
            target_group_url,
            client_id: client_id.to_string(),
        };

        {
            let mut session = self
                .clients
                .entry(client_id.to_string())
                .or_insert_with(|| ClientSession {
                    last_seen: Instant::now(),
                    user_agent: "ChromeExtension".to_string(),
                    pending_jobs: VecDeque::new(),
                });
            session.pending_jobs.push_back(job);
            self.job_to_client
                .insert(job_id.clone(), client_id.to_string());
        }

        info!(
            "[ExtensionBridge] Dispatched job {} to browser extension (client={}).",
            job_id, client_id
        );

        match tokio::time::timeout(Duration::from_secs(timeout_secs), rx).await {
            Ok(Ok(res)) => {
                let status_code = res
                    .get("status_code")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(200);
                let text = res
                    .get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if status_code == 200 && !text.is_empty() {
                    Some(text)
                } else {
                    warn!(
                        "[ExtensionBridge] Job {} returned status={} err={:?}",
                        job_id,
                        status_code,
                        res.get("tab_error")
                    );
                    None
                }
            }
            _ => {
                self.waiters.remove(&job_id);
                self.job_to_client.remove(&job_id);
                if let Some(mut session) = self.clients.get_mut(client_id) {
                    session.pending_jobs.retain(|j| j.id != job_id);
                }
                warn!(
                    "[ExtensionBridge] Job {} timed out after {}s.",
                    job_id, timeout_secs
                );
                None
            }
        }
    }
}
