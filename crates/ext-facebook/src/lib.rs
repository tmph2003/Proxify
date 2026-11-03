use async_trait::async_trait;
use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{header, HeaderMap, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use chrono::Utc;
use dashmap::DashMap;
use parking_lot::RwLock;
use proxify_core::stealth::StealthSessionManager;
use proxify_sdk::{
    BaseExtension, EventPublisher, ExtensionContext, HttpFlow, ObserverInterceptor, TopicHandler,
    UiPageMetadata,
};
use regex::Regex;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::Duration;
use tracing::{info, warn};
use uuid::Uuid;

pub mod bridge;
pub mod parser;
pub mod storage;

use bridge::{BridgeResultPayload, ExtensionBridge};
use parser::{CommentExtractor, DataHelper, PostExtractor};
use storage::FacebookStorage;

#[derive(Clone, Default)]
pub struct TenantAuthData {
    pub cookie: String,
    pub fb_dtsg: String,
    pub lsd: String,
    pub user_agent: String,
    pub user_id: String,
    pub templates: HashMap<String, Value>,
}

pub struct FacebookGraphQLObserver {
    event_bus: Arc<dyn EventPublisher>,
}

impl FacebookGraphQLObserver {
    pub fn new(event_bus: Arc<dyn EventPublisher>) -> Arc<Self> {
        Arc::new(Self { event_bus })
    }
}

#[async_trait]
impl ObserverInterceptor for FacebookGraphQLObserver {
    async fn observe_request(&self, _flow: &HttpFlow) {}

    async fn observe_response(&self, flow: &HttpFlow) {
        let host = flow.request.host.to_lowercase();
        if !host.contains("facebook.com") {
            return;
        }
        if !flow.request.path.contains("/api/graphql") || flow.request.method != "POST" {
            return;
        }
        let resp = match &flow.response {
            Some(r) if r.status_code == 200 => r,
            _ => return,
        };

        let req_body = String::from_utf8_lossy(&flow.request.content).to_string();
        let resp_body = String::from_utf8_lossy(&resp.content).to_string();
        if resp_body.is_empty() {
            return;
        }

        self.event_bus.publish(
            "facebook.graphql.request",
            json!({
                "url": flow.request.url,
                "headers": flow.request.headers,
                "req_body": req_body,
                "resp_body": resp_body,
            }),
        );
    }
}

pub struct FacebookTopicHandler {
    storage: Arc<FacebookStorage>,
    event_bus: Arc<dyn EventPublisher>,
    tenant_auth: Arc<DashMap<String, TenantAuthData>>,
}

impl FacebookTopicHandler {
    pub fn new(
        storage: Arc<FacebookStorage>,
        event_bus: Arc<dyn EventPublisher>,
        tenant_auth: Arc<DashMap<String, TenantAuthData>>,
    ) -> Arc<Self> {
        Arc::new(Self {
            storage,
            event_bus,
            tenant_auth,
        })
    }
}

#[async_trait]
impl TopicHandler for FacebookTopicHandler {
    async fn handle(&self, _topic: &str, payload: &Value) -> Result<(), String> {
        let url = payload.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let headers = payload.get("headers").cloned().unwrap_or_else(|| json!({}));
        let req_body = payload
            .get("req_body")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let resp_body = payload
            .get("resp_body")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let mut form_data = HashMap::new();
        for pair in req_body.split('&') {
            if let Some((k, v)) = pair.split_once('=') {
                let key = urlencoding::decode(k).unwrap_or_default().into_owned();
                let val = urlencoding::decode(v).unwrap_or_default().into_owned();
                form_data.insert(key, val);
            }
        }

        // Capture cookie and fb_dtsg from live proxy traffic into default tenant & DB
        let live_cookie = headers
            .get("cookie")
            .or_else(|| headers.get("Cookie"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        if !live_cookie.is_empty() && live_cookie.contains("c_user=") {
            self.storage
                .save_config_str("fb_cookie", &live_cookie)
                .await;
            let mut entry = self.tenant_auth.entry("default".to_string()).or_default();
            entry.cookie = live_cookie;
        }

        if let Some(dtsg) = form_data.get("fb_dtsg") {
            if !dtsg.is_empty() {
                self.storage.save_config_str("fb_dtsg", dtsg).await;
                if let Some(lsd) = form_data.get("lsd") {
                    self.storage.save_config_str("lsd", lsd).await;
                }
                {
                    let mut entry = self.tenant_auth.entry("default".to_string()).or_default();
                    entry.fb_dtsg = dtsg.clone();
                    if let Some(lsd) = form_data.get("lsd") {
                        entry.lsd = lsd.clone();
                    }
                }
                self.storage
                    .save_config(
                        "last_fb_dtsg",
                        &json!({
                            "url": url,
                            "headers": headers,
                            "form_data": form_data,
                        }),
                    )
                    .await;
            }
        }

        let friendly_name = form_data
            .get("fb_api_req_friendly_name")
            .cloned()
            .or_else(|| {
                headers
                    .get("x-fb-friendly-name")
                    .or_else(|| headers.get("X-FB-Friendly-Name"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string())
            })
            .unwrap_or_default();

        if !friendly_name.is_empty()
            && (friendly_name.contains("Group")
                || friendly_name.contains("Feed")
                || friendly_name.contains("Timeline")
                || friendly_name.contains("Comment")
                || friendly_name.contains("FocusedStory"))
        {
            let tpl_val = json!({
                "url": url,
                "headers": headers,
                "form_data": form_data,
            });
            self.storage
                .save_config(&format!("template_{}", friendly_name), &tpl_val)
                .await;

            let mut entry = self.tenant_auth.entry("default".to_string()).or_default();
            if friendly_name.contains("Comment") || friendly_name.contains("UFI") {
                entry.templates.insert("comment".to_string(), tpl_val);
            } else {
                entry.templates.insert("feed".to_string(), tpl_val);
            }
        }

        let nodes = DataHelper::extract_nodes(resp_body);
        let mut saved_posts = 0;
        for node in &nodes {
            if let Some(post) = PostExtractor::extract(node, None) {
                if self.storage.save_post(&post).await {
                    saved_posts += 1;
                    self.event_bus.broadcast_ws("fb_new_post", post);
                }
            }
        }

        if saved_posts == 0 {
            let mut target_post_id = String::new();
            if let Some(vars_str) = form_data.get("variables") {
                if let Ok(vars) = serde_json::from_str::<Value>(vars_str) {
                    if let Some(pid) = DataHelper::extract_canonical_post_id(&vars) {
                        target_post_id = pid;
                    }
                }
            }
            if !target_post_id.is_empty() {
                for line in resp_body.lines() {
                    let trimmed = line.trim().trim_start_matches("for (;;);");
                    if let Ok(parsed) = serde_json::from_str::<Value>(trimmed) {
                        let comments =
                            CommentExtractor::extract_all_from_node(&parsed, &target_post_id);
                        if !comments.is_empty() {
                            let c_saved = self
                                .storage
                                .save_standalone_comments(&comments, &target_post_id)
                                .await;
                            if c_saved > 0 {
                                self.event_bus.broadcast_ws(
                                    "fb_new_comments",
                                    json!({ "post_id": target_post_id, "count": c_saved }),
                                );
                            }
                        }
                    }
                }
            }
        }

        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct FeedCrawlParams {
    pub target_type: String,
    pub target_id: String,
    pub max_pages: usize,
    pub target_posts: usize,
    pub client_id: String,
    pub cookie_override: Option<String>,
    pub dtsg_override: Option<String>,
}

pub struct FacebookCrawlerEngine {
    pub storage: Arc<FacebookStorage>,
    pub bridge: Arc<ExtensionBridge>,
    pub stealth: Arc<StealthSessionManager>,
    pub event_bus: Arc<dyn EventPublisher>,
    pub tenant_auth: Arc<DashMap<String, TenantAuthData>>,
    pub is_running: AtomicBool,
    pub is_comment_running: AtomicBool,
    pub group_crawl_state: RwLock<Value>,
    pub refresh_progress: RwLock<Value>,
    pub comment_progress: DashMap<String, Value>,
    pub bulk_progress: DashMap<String, Value>,
}

impl FacebookCrawlerEngine {
    pub fn new(
        storage: Arc<FacebookStorage>,
        bridge: Arc<ExtensionBridge>,
        event_bus: Arc<dyn EventPublisher>,
        tenant_auth: Arc<DashMap<String, TenantAuthData>>,
    ) -> Arc<Self> {
        Arc::new(Self {
            storage,
            bridge,
            stealth: Arc::new(StealthSessionManager::new(2, None)),
            event_bus,
            tenant_auth,
            is_running: AtomicBool::new(false),
            is_comment_running: AtomicBool::new(false),
            group_crawl_state: RwLock::new(json!({
                "status": "idle",
                "group_id": "",
                "message": "Sẵn sàng thu thập dữ liệu",
                "updated_at": Utc::now().to_rfc3339(),
                "last_p_count": 0,
                "last_c_count": 0,
            })),
            refresh_progress: RwLock::new(json!({
                "total": 0,
                "current": 0,
                "status": "idle",
            })),
            comment_progress: DashMap::new(),
            bulk_progress: DashMap::new(),
        })
    }

    pub fn get_status(&self) -> Value {
        let mut comment_crawls = serde_json::Map::new();
        for item in self.comment_progress.iter() {
            comment_crawls.insert(item.key().clone(), item.value().clone());
        }

        let is_post = self.is_running.load(Ordering::Relaxed);
        let is_comment = self.is_comment_running.load(Ordering::Relaxed);
        let group_state = self.group_crawl_state.read().clone();
        let refresh = self.refresh_progress.read().clone();

        json!({
            "is_running": is_post,
            "is_post_crawling": is_post,
            "is_comment_crawling": is_comment,
            "status": group_state.get("message").and_then(|v| v.as_str()).unwrap_or("IDLE"),
            "group_crawl": group_state,
            "refresh": refresh,
            "comment_crawls": Value::Object(comment_crawls),
            "circuit_breaker": self.stealth.circuit_breaker.state().as_str(),
            "bridge_connected": self.bridge.is_connected(),
        })
    }

    pub fn stop(&self) {
        self.is_running.store(false, Ordering::Relaxed);
        let mut g = self.group_crawl_state.write();
        g["status"] = json!("idle");
        g["message"] = json!("Đã dừng thu thập dữ liệu.");
        g["updated_at"] = json!(Utc::now().to_rfc3339());
    }

    pub fn stop_comment_crawl(&self, post_id: Option<&str>) {
        self.is_comment_running.store(false, Ordering::Relaxed);
        if let Some(pid) = post_id {
            self.comment_progress.insert(
                pid.to_string(),
                json!({
                    "status": "idle",
                    "total": 0,
                    "message": "Đã dừng cào bình luận."
                }),
            );
        } else {
            for mut item in self.comment_progress.iter_mut() {
                *item.value_mut() = json!({
                    "status": "idle",
                    "total": 0,
                    "message": "Đã dừng cào bình luận."
                });
            }
        }
    }

    pub fn trigger_feed_crawl(self: &Arc<Self>, params: FeedCrawlParams) -> Result<(), String> {
        let FeedCrawlParams {
            target_type,
            target_id,
            max_pages,
            target_posts,
            client_id,
            cookie_override,
            dtsg_override,
        } = params;

        if self.is_comment_running.load(Ordering::Relaxed) {
            return Err(
                "⚠️ Đang có tiến trình cào bình luận đang chạy. Vui lòng chờ hoàn tất.".to_string(),
            );
        }
        if self.is_running.swap(true, Ordering::SeqCst) {
            return Err("Tiến trình cào bài viết đang chạy.".to_string());
        }

        if let Some(c) = cookie_override.filter(|s| !s.is_empty()) {
            let mut entry = self.tenant_auth.entry(client_id.clone()).or_default();
            entry.cookie = c;
        }
        if let Some(d) = dtsg_override.filter(|s| !s.is_empty()) {
            let mut entry = self.tenant_auth.entry(client_id.clone()).or_default();
            entry.fb_dtsg = d;
        }

        {
            let mut g = self.group_crawl_state.write();
            g["status"] = json!("running");
            g["group_id"] = json!(target_id);
            g["message"] = json!(format!(
                "🚀 Đang thu thập dữ liệu {} {}...",
                target_type, target_id
            ));
            g["updated_at"] = json!(Utc::now().to_rfc3339());
            g["last_p_count"] = json!(0);
            g["last_c_count"] = json!(0);
        }

        let engine = self.clone();
        tokio::spawn(async move {
            engine
                .run_feed_crawl(
                    &target_type,
                    &target_id,
                    max_pages,
                    target_posts,
                    &client_id,
                )
                .await;
            engine.is_running.store(false, Ordering::SeqCst);
        });
        Ok(())
    }

    pub fn trigger_comment_crawl(
        self: &Arc<Self>,
        post_id: String,
        feedback_id: Option<String>,
        client_id: String,
        cookie_override: Option<String>,
        dtsg_override: Option<String>,
    ) -> Result<(), String> {
        if self.is_running.load(Ordering::Relaxed) {
            return Err(
                "⚠️ Đang có tiến trình cào bài viết đang chạy. Vui lòng chờ hoàn tất.".to_string(),
            );
        }

        if let Some(c) = cookie_override.filter(|s| !s.is_empty()) {
            let mut entry = self.tenant_auth.entry(client_id.clone()).or_default();
            entry.cookie = c;
        }
        if let Some(d) = dtsg_override.filter(|s| !s.is_empty()) {
            let mut entry = self.tenant_auth.entry(client_id.clone()).or_default();
            entry.fb_dtsg = d;
        }

        self.comment_progress.insert(
            post_id.clone(),
            json!({
                "status": "running",
                "total": 0,
                "message": "Đang gửi yêu cầu cào bình luận..."
            }),
        );

        let engine = self.clone();
        tokio::spawn(async move {
            engine.is_comment_running.store(true, Ordering::SeqCst);
            engine
                .run_single_comment_crawl(&post_id, feedback_id.as_deref(), &client_id)
                .await;
            engine.is_comment_running.store(false, Ordering::SeqCst);
        });
        Ok(())
    }

    async fn execute_request(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        form_data: &HashMap<String, String>,
        target_group_url: Option<&str>,
        client_id: &str,
    ) -> Option<String> {
        let mut hdrs = headers.clone();
        if let Some(turl) = target_group_url {
            hdrs.entry("referer".to_string())
                .or_insert_with(|| turl.to_string());
        }
        if self.bridge.is_connected() {
            if let Some(resp) = self
                .bridge
                .execute_graphql_for_client(client_id, url, &hdrs, form_data, 30)
                .await
            {
                return Some(resp);
            }
        }
        self.stealth.post_graphql(url, &hdrs, form_data, 3).await
    }

    async fn load_template_with_fresh_dtsg(
        &self,
        candidates: &[&str],
        client_id: &str,
    ) -> Option<(String, HashMap<String, String>, HashMap<String, String>)> {
        let tenant = self
            .tenant_auth
            .get(client_id)
            .map(|r| r.value().clone())
            .or_else(|| self.tenant_auth.get("default").map(|r| r.value().clone()))
            .unwrap_or_default();

        let dtsg_cfg = self.storage.load_config("last_fb_dtsg").await;
        let mut tpl_cfg = None;
        for name in candidates {
            if let Some(cfg) = self
                .storage
                .load_config(&format!("template_{}", name))
                .await
            {
                tpl_cfg = Some(cfg);
                break;
            }
        }
        if tpl_cfg.is_none() {
            if candidates
                .iter()
                .any(|c| c.contains("Comment") || c.contains("UFI"))
            {
                tpl_cfg = tenant.templates.get("comment").cloned();
            } else {
                tpl_cfg = tenant.templates.get("feed").cloned();
            }
        }

        let tpl = tpl_cfg
            .or_else(|| dtsg_cfg.clone())
            .unwrap_or_else(|| json!({}));
        let url = tpl
            .get("url")
            .and_then(|v| v.as_str())
            .unwrap_or("https://www.facebook.com/api/graphql/")
            .to_string();

        let mut headers: HashMap<String, String> = serde_json::from_value(
            tpl.get("headers")
                .or_else(|| dtsg_cfg.as_ref().and_then(|d| d.get("headers")))
                .cloned()
                .unwrap_or_else(|| json!({})),
        )
        .unwrap_or_default();

        let mut form_data: HashMap<String, String> = serde_json::from_value(
            tpl.get("form_data")
                .or_else(|| dtsg_cfg.as_ref().and_then(|d| d.get("form_data")))
                .cloned()
                .unwrap_or_else(|| json!({})),
        )
        .unwrap_or_default();

        let active_cookie = if !tenant.cookie.is_empty() {
            tenant.cookie.clone()
        } else {
            self.storage
                .load_config_str("fb_cookie")
                .await
                .unwrap_or_default()
        };
        if !active_cookie.is_empty() {
            headers.insert("cookie".to_string(), active_cookie);
        }

        let active_dtsg = if !tenant.fb_dtsg.is_empty() {
            tenant.fb_dtsg
        } else if let Some(d) = dtsg_cfg
            .as_ref()
            .and_then(|c| c.get("form_data"))
            .and_then(|f| f.get("fb_dtsg"))
            .and_then(|v| v.as_str())
        {
            d.to_string()
        } else {
            self.storage
                .load_config_str("fb_dtsg")
                .await
                .unwrap_or_default()
        };

        if active_dtsg.is_empty() && !self.bridge.is_connected() {
            return None;
        }
        if !active_dtsg.is_empty() {
            form_data.insert("fb_dtsg".to_string(), active_dtsg);
        }
        if !tenant.lsd.is_empty() {
            form_data.insert("lsd".to_string(), tenant.lsd);
        }

        Some((url, headers, form_data))
    }

    async fn run_feed_crawl(
        &self,
        mode: &str,
        target_id: &str,
        max_pages: usize,
        target_posts: usize,
        client_id: &str,
    ) {
        let candidates = if mode == "group" {
            vec![
                "GroupsCometFeedRegularStoriesPaginationQuery",
                "CometModernHomeFeedQuery",
            ]
        } else {
            vec![
                "ProfileCometTimelineFeedRefetchQuery",
                "ProfileCometTimelineFeedQuery",
            ]
        };

        let (url, headers, mut form_data) = match self
            .load_template_with_fresh_dtsg(&candidates, client_id)
            .await
        {
            Some(t) => t,
            None => {
                warn!("[FacebookCrawler] Missing fb_dtsg or GraphQL template. Browse Facebook or sync via Extension first.");
                let mut g = self.group_crawl_state.write();
                g["status"] = json!("error");
                g["message"] = json!("⚠️ Chưa nhận được fb_dtsg hoặc GraphQL Template. Hãy mở tab Facebook hoặc bấm 'Bắn Cookie vào Proxify' trên Extension!");
                g["updated_at"] = json!(Utc::now().to_rfc3339());
                return;
            }
        };

        let target_url = if mode == "group" {
            format!("https://www.facebook.com/groups/{}", target_id)
        } else {
            format!("https://www.facebook.com/{}", target_id)
        };

        let mut cursor: Option<String> = None;
        let mut total_collected = 0;

        for page in 0..max_pages {
            if !self.is_running.load(Ordering::Relaxed) || total_collected >= target_posts {
                break;
            }

            let mut vars: Value = form_data
                .get("variables")
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or_else(|| json!({}));

            if let Some(obj) = vars.as_object_mut() {
                obj.insert("id".to_string(), json!(target_id));
                obj.insert("groupID".to_string(), json!(target_id));
                if let Some(ref cur) = cursor {
                    obj.insert("cursor".to_string(), json!(cur));
                }
            }
            form_data.insert("variables".to_string(), vars.to_string());

            let resp_text = match self
                .execute_request(&url, &headers, &form_data, Some(&target_url), client_id)
                .await
            {
                Some(t) => t,
                None => break,
            };

            let nodes = DataHelper::extract_nodes(&resp_text);
            let mut page_posts = 0;
            for node in &nodes {
                if let Some(post) = PostExtractor::extract(node, Some(target_id)) {
                    if self.storage.save_post(&post).await {
                        total_collected += 1;
                        page_posts += 1;
                        self.event_bus.broadcast_ws("fb_new_post", post);
                    }
                }
            }

            {
                let mut g = self.group_crawl_state.write();
                g["status"] = json!("running");
                g["message"] = json!(format!(
                    "Đang thu thập trang {}/{} (Đã lưu {} bài viết)...",
                    page + 1,
                    max_pages,
                    total_collected
                ));
                g["last_p_count"] = json!(page_posts);
                g["updated_at"] = json!(Utc::now().to_rfc3339());
            }

            let mut next_cursor = None;
            for line in resp_text.lines() {
                if let Ok(parsed) =
                    serde_json::from_str::<Value>(line.trim().trim_start_matches("for (;;);"))
                {
                    for pi in DataHelper::find_key(&parsed, "page_info") {
                        if pi
                            .get("has_next_page")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false)
                        {
                            if let Some(ec) = pi.get("end_cursor").and_then(|v| v.as_str()) {
                                next_cursor = Some(ec.to_string());
                                break;
                            }
                        }
                    }
                }
            }

            info!(
                "[FacebookCrawler] {}={} page={}/{} collected={}",
                mode,
                target_id,
                page + 1,
                max_pages,
                total_collected
            );

            match next_cursor {
                Some(c) => cursor = Some(c),
                None => break,
            }
        }

        let mut g = self.group_crawl_state.write();
        g["status"] = json!("idle");
        g["message"] = json!(format!(
            "✅ Hoàn tất thu thập ({} bài viết mới).",
            total_collected
        ));
        g["last_p_count"] = json!(total_collected);
        g["updated_at"] = json!(Utc::now().to_rfc3339());
    }

    async fn run_single_comment_crawl(
        &self,
        post_id: &str,
        feedback_id_opt: Option<&str>,
        client_id: &str,
    ) {
        let candidates = [
            "CommentListComponentsRootQuery",
            "CometFocusedStoryViewUFIQuery",
        ];
        let (url, headers, mut form_data) = match self
            .load_template_with_fresh_dtsg(&candidates, client_id)
            .await
        {
            Some(t) => t,
            None => {
                self.comment_progress.insert(
                    post_id.to_string(),
                    json!({
                        "status": "error",
                        "total": 0,
                        "message": "Chưa có fb_dtsg hoặc Comment Template."
                    }),
                );
                return;
            }
        };

        let mut vars: Value = form_data
            .get("variables")
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));

        let feedback_b64 = match feedback_id_opt.filter(|s| !s.is_empty()) {
            Some(f) => f.to_string(),
            None => {
                use base64::Engine;
                base64::engine::general_purpose::STANDARD.encode(format!("feedback:{}", post_id))
            }
        };

        if let Some(obj) = vars.as_object_mut() {
            obj.insert("feedbackID".to_string(), json!(feedback_b64));
            obj.insert("storyID".to_string(), json!(post_id));
        }
        form_data.insert("variables".to_string(), vars.to_string());

        let post_url = format!("https://www.facebook.com/{}", post_id);
        let mut total_saved = 0;

        if let Some(resp_text) = self
            .execute_request(&url, &headers, &form_data, Some(&post_url), client_id)
            .await
        {
            for line in resp_text.lines() {
                if let Ok(parsed) =
                    serde_json::from_str::<Value>(line.trim().trim_start_matches("for (;;);"))
                {
                    let comments = CommentExtractor::extract_all_from_node(&parsed, post_id);
                    if !comments.is_empty() {
                        let cnt = self
                            .storage
                            .save_standalone_comments(&comments, post_id)
                            .await;
                        total_saved += cnt;
                        if cnt > 0 {
                            self.event_bus.broadcast_ws(
                                "fb_new_comments",
                                json!({ "post_id": post_id, "count": cnt }),
                            );
                        }
                    }
                }
            }
        }

        self.comment_progress.insert(
            post_id.to_string(),
            json!({
                "status": "done",
                "total": total_saved,
                "message": format!("Hoàn tất ({} bình luận)", total_saved)
            }),
        );
    }
}

#[derive(Clone)]
struct FacebookRouteState {
    storage: Arc<FacebookStorage>,
    bridge: Arc<ExtensionBridge>,
    crawler: Arc<FacebookCrawlerEngine>,
    tenant_auth: Arc<DashMap<String, TenantAuthData>>,
    ext_dir: PathBuf,
}

#[derive(Deserialize)]
struct PostsQuery {
    group_id: Option<String>,
    search: Option<String>,
    has_links: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Deserialize)]
struct ResultsQuery {
    sort: Option<String>,
    order: Option<String>,
    group_id: Option<String>,
    group_name: Option<String>,
    status: Option<String>,
    start_date: Option<String>,
    end_date: Option<String>,
    page: Option<i64>,
    limit: Option<i64>,
}

#[derive(Deserialize)]
struct CrawlRequest {
    target_type: Option<String>,
    target_id: Option<String>,
    group_id: Option<String>,
    profile_id: Option<String>,
    max_pages: Option<usize>,
    target_posts: Option<usize>,
    cookie: Option<String>,
    fb_dtsg: Option<String>,
    client_id: Option<String>,
}

#[derive(Deserialize)]
struct CrawlCommentsRequest {
    post_id: String,
    feedback_id: Option<String>,
    group_id: Option<String>,
    cookie: Option<String>,
    fb_dtsg: Option<String>,
    client_id: Option<String>,
}

#[derive(Deserialize)]
struct StopCommentCrawlRequest {
    post_id: Option<String>,
}

#[derive(Deserialize)]
struct PostIdQuery {
    post_id: Option<String>,
}

#[derive(Deserialize)]
struct TaskIdQuery {
    task_id: Option<String>,
}

#[derive(Deserialize)]
struct ClientIdQuery {
    client_id: Option<String>,
}

#[derive(Deserialize)]
struct SaveCookieRequest {
    cookie: Option<String>,
    user_agent: Option<String>,
    fb_dtsg: Option<String>,
    lsd: Option<String>,
    user_id: Option<String>,
    client_id: Option<String>,
    friendly_name: Option<String>,
    feed_template: Option<Value>,
}

#[derive(Deserialize)]
struct PostStatusPatchRequest {
    post_ids: Vec<String>,
    is_active: Option<bool>,
}

#[derive(Deserialize)]
struct BulkActionRequest {
    action: String,
    post_ids: Vec<String>,
    cookie: Option<String>,
    client_id: Option<String>,
}

pub struct FacebookExtension {
    ext_dir: PathBuf,
}

impl FacebookExtension {
    pub fn new(ext_dir: PathBuf) -> Self {
        Self { ext_dir }
    }
}

#[async_trait]
impl BaseExtension for FacebookExtension {
    fn name(&self) -> &str {
        "facebook"
    }

    async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        let storage = FacebookStorage::new(context.db_pool().clone());
        storage.init_schema().await?;

        // Register Facebook-specific GraphQL query parameter aliases dynamically
        proxify_core::graphql::GraphQLParser::register_operation_alias("fb_api_req_friendly_name");
        proxify_core::graphql::GraphQLParser::register_query_alias("doc_id");

        // Register Facebook Graph API checkpoint/block signatures
        const FB_CHECKPOINT_SIGNATURES: &[&str] = &[
            "\"error\":1357001",
            "\"error\":1357004",
            "\"error\":1357031",
            "\"error\":1404002",
            "\"error\":1675030",
            "\"error\":1675012",
            "\"is_checkpoint\":true",
            "/checkpoint/block",
        ];
        for sig in FB_CHECKPOINT_SIGNATURES {
            context.register_soft_block_signature(sig);
            proxify_core::stealth::register_soft_block_signature(sig);
        }

        let tenant_auth: Arc<DashMap<String, TenantAuthData>> = Arc::new(DashMap::new());
        if let Some(saved_cookie) = storage.load_config_str("fb_cookie").await {
            let saved_dtsg = storage.load_config_str("fb_dtsg").await.unwrap_or_default();
            let saved_lsd = storage.load_config_str("lsd").await.unwrap_or_default();
            tenant_auth.insert(
                "default".to_string(),
                TenantAuthData {
                    cookie: saved_cookie,
                    fb_dtsg: saved_dtsg,
                    lsd: saved_lsd,
                    ..Default::default()
                },
            );
        }

        let observer = FacebookGraphQLObserver::new(context.event_bus());
        context.register_observer("*.facebook.com", observer.clone());
        context.register_observer("facebook.com", observer);

        for stream_domain in ["*.fbcdn.net", "*.fbsbx.com"] {
            context.register_stream_rule(stream_domain);
        }

        let handler =
            FacebookTopicHandler::new(storage.clone(), context.event_bus(), tenant_auth.clone());
        context.subscribe_topic("facebook.graphql.request", handler);

        let bridge = ExtensionBridge::new();
        let crawler = FacebookCrawlerEngine::new(
            storage.clone(),
            bridge.clone(),
            context.event_bus.clone(),
            tenant_auth.clone(),
        );

        let state = FacebookRouteState {
            storage,
            bridge,
            crawler,
            tenant_auth,
            ext_dir: self.ext_dir.clone(),
        };

        let router = Router::new()
            .route("/facebook", get(handle_fb_ui))
            .route("/api/facebook/static/:file", get(handle_fb_static))
            .route("/api/facebook/groups", get(handle_fb_groups))
            .route("/api/facebook/results", get(handle_fb_results))
            .route("/api/facebook/posts", get(handle_fb_posts))
            .route("/api/facebook/posts/:id", get(handle_fb_post_detail))
            .route("/api/facebook/stats", get(handle_fb_stats))
            .route("/api/facebook/token_status", get(handle_fb_token_status))
            .route(
                "/api/facebook/cookie",
                get(handle_get_cookie).post(handle_save_cookie),
            )
            .route("/api/facebook/crawl", post(handle_fb_crawl))
            .route("/api/facebook/crawl_profile", post(handle_fb_crawl))
            .route("/api/facebook/stop_crawl", post(handle_fb_crawl_stop))
            .route("/api/facebook/crawl/stop", post(handle_fb_crawl_stop))
            .route("/api/facebook/crawl_status", get(handle_fb_crawl_status))
            .route("/api/facebook/crawl/status", get(handle_fb_crawl_status))
            .route("/api/facebook/comments", get(handle_get_comments))
            .route(
                "/api/facebook/crawl_comments",
                post(handle_fb_crawl_comments),
            )
            .route("/api/facebook/comment_status", get(handle_comment_status))
            .route(
                "/api/facebook/stop_comment_crawl",
                post(handle_stop_comment_crawl),
            )
            .route("/api/facebook/post_status", patch(handle_patch_post_status))
            .route("/api/facebook/bulk_action", post(handle_bulk_action))
            .route("/api/facebook/bulk_status", get(handle_bulk_status))
            .route("/api/facebook/bridge/status", get(handle_bridge_status))
            .route("/api/facebook/bridge/jobs", get(handle_bridge_jobs))
            .route("/api/facebook/bridge/result", post(handle_bridge_result))
            .with_state(state);

        context.register_sub_router(router);
        context.register_ui_page(UiPageMetadata {
            name: "facebook".to_string(),
            path: "/facebook".to_string(),
            title: "Facebook Extractor".to_string(),
            icon: "📘".to_string(),
            description: "Facebook GraphQL Intelligence & Multi-Tenant Bridge Crawler".to_string(),
            order: 20,
        });

        info!(
            "[Extension: Facebook] Initialized GraphQL Observer, CQRS Worker, Bridge & Crawlers."
        );
        Ok(())
    }
}

async fn handle_fb_ui(State(state): State<FacebookRouteState>) -> Response {
    let html_path = state.ext_dir.join("static").join("facebook.html");
    match tokio::fs::read_to_string(&html_path).await {
        Ok(html) => Html(html).into_response(),
        Err(_) => Html("<h1>Facebook Feed Intelligence</h1>".to_string()).into_response(),
    }
}

async fn handle_fb_static(
    State(state): State<FacebookRouteState>,
    AxumPath(file): AxumPath<String>,
) -> Response {
    if file.contains("..") || file.contains('/') || file.contains('\\') {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let path = state.ext_dir.join("static").join(&file);
    let ct = if file.ends_with(".js") {
        "application/javascript; charset=utf-8"
    } else if file.ends_with(".css") {
        "text/css; charset=utf-8"
    } else {
        "text/html; charset=utf-8"
    };
    match tokio::fs::read(&path).await {
        Ok(bytes) => ([(header::CONTENT_TYPE, ct)], bytes).into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

async fn handle_fb_groups(State(state): State<FacebookRouteState>) -> Json<Value> {
    Json(state.storage.get_groups_list().await)
}

async fn handle_fb_results(
    State(state): State<FacebookRouteState>,
    Query(q): Query<ResultsQuery>,
) -> Json<Value> {
    let sort = q.sort.as_deref().unwrap_or("time");
    let order = q.order.as_deref().unwrap_or("DESC");
    let group_id = q.group_id.as_deref().unwrap_or("");
    let group_name = q.group_name.as_deref().unwrap_or("");
    let status = q.status.as_deref().unwrap_or("");
    let start_date = q.start_date.as_deref().unwrap_or("");
    let end_date = q.end_date.as_deref().unwrap_or("");
    let page = q.page.unwrap_or(1);
    let limit = q.limit.unwrap_or(20);

    Json(
        state
            .storage
            .query_results(
                sort, order, group_id, group_name, status, start_date, end_date, page, limit,
            )
            .await,
    )
}

async fn handle_fb_posts(
    State(state): State<FacebookRouteState>,
    Query(q): Query<PostsQuery>,
) -> Json<Value> {
    let has_links = matches!(q.has_links.as_deref(), Some("true") | Some("1"));
    let limit = q.limit.unwrap_or(50).clamp(1, 500);
    let offset = q.offset.unwrap_or(0).max(0);
    Json(
        state
            .storage
            .get_posts(
                q.group_id.as_deref(),
                q.search.as_deref(),
                has_links,
                limit,
                offset,
            )
            .await,
    )
}

async fn handle_fb_post_detail(
    State(state): State<FacebookRouteState>,
    AxumPath(id): AxumPath<String>,
) -> Response {
    match state.storage.get_post_detail(&id).await {
        Some(detail) => Json(detail).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "Post not found" })),
        )
            .into_response(),
    }
}

async fn handle_fb_stats(State(state): State<FacebookRouteState>) -> Json<Value> {
    Json(state.storage.get_stats().await)
}

async fn handle_fb_token_status(State(state): State<FacebookRouteState>) -> Json<Value> {
    Json(state.storage.get_token_status().await)
}

async fn handle_get_cookie(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Query(q): Query<ClientIdQuery>,
) -> Json<Value> {
    let client_id = q
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    let mut cookie = state
        .tenant_auth
        .get(&client_id)
        .map(|c| c.cookie.clone())
        .unwrap_or_default();

    if cookie.is_empty() {
        cookie = state
            .tenant_auth
            .get("default")
            .map(|c| c.cookie.clone())
            .unwrap_or_default();
    }
    if cookie.is_empty() {
        cookie = state
            .storage
            .load_config_str("fb_cookie")
            .await
            .unwrap_or_default();
    }

    Json(json!({
        "status": "ok",
        "cookie": cookie,
        "client_id": client_id,
    }))
}

async fn handle_save_cookie(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Json(req): Json<SaveCookieRequest>,
) -> Response {
    let client_id = req
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    let mut cookie_str = req.cookie.unwrap_or_default().trim().to_string();
    let user_agent = req.user_agent.unwrap_or_default().trim().to_string();
    let fb_dtsg = req.fb_dtsg.unwrap_or_default().trim().to_string();
    let lsd = req.lsd.unwrap_or_default().trim().to_string();
    let user_id = req.user_id.unwrap_or_default().trim().to_string();
    let friendly_name = req.friendly_name.unwrap_or_else(|| "Unknown".to_string());

    let mut tpl_cookie = String::new();
    if let Some(ref tpl) = req.feed_template {
        if let Some(hdrs) = tpl.get("headers") {
            tpl_cookie = hdrs
                .get("cookie")
                .or_else(|| hdrs.get("Cookie"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
        }
        state
            .storage
            .save_config(&format!("template_{}", friendly_name), tpl)
            .await;
    }

    if cookie_str.is_empty() && req.feed_template.is_none() && fb_dtsg.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": "No cookie or template provided" })),
        )
            .into_response();
    }

    if !user_id.is_empty() && !cookie_str.is_empty() && !cookie_str.contains("c_user=") {
        cookie_str = format!("c_user={}; {}", user_id, cookie_str);
    }

    static RE_XS: OnceLock<Regex> = OnceLock::new();
    let re_xs = RE_XS.get_or_init(|| Regex::new(r"xs=([^;]+)").unwrap());

    let (final_cookie, has_dtsg) = {
        let mut entry = state.tenant_auth.entry(client_id.clone()).or_default();

        if let Some(tpl) = req.feed_template {
            if friendly_name.contains("Depth") || friendly_name.contains("Reply") {
                entry.templates.insert("reply".to_string(), tpl);
            } else if friendly_name.contains("Comment") || friendly_name.contains("UFI") {
                entry.templates.insert("comment".to_string(), tpl);
            } else {
                entry.templates.insert("feed".to_string(), tpl);
            }
        }

        if !tpl_cookie.is_empty() {
            if tpl_cookie.contains("xs=") && !entry.cookie.contains("xs=") {
                if let Some(caps) = re_xs.captures(&tpl_cookie) {
                    if !entry.cookie.is_empty() {
                        entry.cookie = format!("{}; xs={}", entry.cookie, &caps[1]);
                    } else {
                        entry.cookie = tpl_cookie;
                    }
                }
            } else if entry.cookie.is_empty() {
                entry.cookie = tpl_cookie;
            }
        }

        if !cookie_str.is_empty() {
            if !cookie_str.contains("xs=") && entry.cookie.contains("xs=") {
                if let Some(caps) = re_xs.captures(&entry.cookie) {
                    cookie_str = format!("{}; xs={}", cookie_str, &caps[1]);
                }
            }
            entry.cookie = cookie_str.clone();
        }
        if !user_agent.is_empty() {
            entry.user_agent = user_agent;
        }
        if !fb_dtsg.is_empty() {
            entry.fb_dtsg = fb_dtsg.clone();
        }
        if !lsd.is_empty() {
            entry.lsd = lsd.clone();
        }
        if !user_id.is_empty() {
            entry.user_id = user_id.clone();
        }

        (entry.cookie.clone(), !entry.fb_dtsg.is_empty())
    };

    // Mirror into default tenant as well so UI & Extension always share state
    if client_id != "default" {
        if let Some(src) = state.tenant_auth.get(&client_id).map(|v| v.value().clone()) {
            let mut def = state.tenant_auth.entry("default".to_string()).or_default();
            if !src.cookie.is_empty() {
                def.cookie = src.cookie;
            }
            if !src.fb_dtsg.is_empty() {
                def.fb_dtsg = src.fb_dtsg;
            }
            if !src.lsd.is_empty() {
                def.lsd = src.lsd;
            }
            for (k, v) in src.templates {
                def.templates.insert(k, v);
            }
        }
    }

    if !final_cookie.is_empty() {
        state
            .storage
            .save_config_str("fb_cookie", &final_cookie)
            .await;
    }
    if !fb_dtsg.is_empty() {
        state.storage.save_config_str("fb_dtsg", &fb_dtsg).await;
    }
    if !lsd.is_empty() {
        state.storage.save_config_str("lsd", &lsd).await;
    }

    let has_c_user = final_cookie.contains("c_user=") || !user_id.is_empty();
    let has_xs = final_cookie.contains("xs=");

    let msg = if has_c_user && has_xs && has_dtsg {
        format!(
            "✅ Đồng bộ HOÀN HẢO (Client: {}). Sẵn sàng crawl!",
            client_id
        )
    } else if has_c_user && has_dtsg {
        format!(
            "⚠️ Đã lưu UID & fb_dtsg (Client: {}). Hệ thống sẽ dùng Extension Tab để xác thực.",
            client_id
        )
    } else if !final_cookie.is_empty() {
        format!(
            "✅ Cookie đã lưu ({} ký tự cho {}).",
            final_cookie.len(),
            client_id
        )
    } else {
        format!(
            "✅ Đã lưu template {} từ extension ({}).",
            friendly_name, client_id
        )
    };

    Json(json!({
        "status": "ok",
        "message": msg,
        "client_id": client_id,
        "has_xs": has_xs,
        "has_c_user": has_c_user,
        "has_dtsg": has_dtsg,
    }))
    .into_response()
}

async fn handle_fb_crawl(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Json(req): Json<CrawlRequest>,
) -> Response {
    let target_type = req.target_type.unwrap_or_else(|| {
        if req.profile_id.is_some() {
            "profile".to_string()
        } else {
            "group".to_string()
        }
    });
    let target_id = req
        .target_id
        .or(req.group_id)
        .or(req.profile_id)
        .unwrap_or_default()
        .trim()
        .to_string();

    if target_id.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": "Missing Group ID / Profile ID" })),
        )
            .into_response();
    }

    let client_id = req
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    match state.crawler.trigger_feed_crawl(FeedCrawlParams {
        target_type,
        target_id,
        max_pages: req.max_pages.unwrap_or(5),
        target_posts: req.target_posts.unwrap_or(30),
        client_id,
        cookie_override: req.cookie,
        dtsg_override: req.fb_dtsg,
    }) {
        Ok(_) => Json(json!({ "status": "ok", "message": "Crawler started" })).into_response(),
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": e })),
        )
            .into_response(),
    }
}

async fn handle_get_comments(
    State(state): State<FacebookRouteState>,
    Query(q): Query<PostIdQuery>,
) -> Response {
    let post_id = q.post_id.unwrap_or_default();
    if post_id.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": "post_id is required" })),
        )
            .into_response();
    }
    Json(state.storage.get_comments_for_post(&post_id).await).into_response()
}

async fn handle_fb_crawl_comments(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Json(req): Json<CrawlCommentsRequest>,
) -> Response {
    let client_id = req
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    match state.crawler.trigger_comment_crawl(
        req.post_id.clone(),
        req.feedback_id.or(req.group_id),
        client_id,
        req.cookie,
        req.fb_dtsg,
    ) {
        Ok(_) => Json(json!({
            "status": "ok",
            "message": format!("Comment crawl started for {}", req.post_id)
        }))
        .into_response(),
        Err(e) => (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": e })),
        )
            .into_response(),
    }
}

async fn handle_comment_status(
    State(state): State<FacebookRouteState>,
    Query(q): Query<PostIdQuery>,
) -> Json<Value> {
    let post_id = q.post_id.unwrap_or_default();
    let progress = state
        .crawler
        .comment_progress
        .get(&post_id)
        .map(|v| v.value().clone())
        .unwrap_or_else(|| json!({ "status": "idle", "total": 0, "message": "" }));
    Json(json!({ "status": "ok", "progress": progress }))
}

async fn handle_stop_comment_crawl(
    State(state): State<FacebookRouteState>,
    Json(req): Json<StopCommentCrawlRequest>,
) -> Json<Value> {
    state.crawler.stop_comment_crawl(req.post_id.as_deref());
    Json(json!({
        "status": "ok",
        "message": "Đã gửi lệnh dừng cào bình luận."
    }))
}

async fn handle_patch_post_status(
    State(state): State<FacebookRouteState>,
    Json(req): Json<PostStatusPatchRequest>,
) -> Json<Value> {
    let updated = state
        .storage
        .update_post_status(&req.post_ids, req.is_active)
        .await;
    Json(json!({ "status": "ok", "updated": updated }))
}

async fn handle_bulk_action(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Json(req): Json<BulkActionRequest>,
) -> Response {
    if req.post_ids.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": "post_ids required" })),
        )
            .into_response();
    }

    let client_id = req
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    match req.action.as_str() {
        "delete" => {
            let deleted = state.storage.delete_posts(&req.post_ids).await;
            Json(json!({ "status": "ok", "deleted": deleted })).into_response()
        }
        "export_csv" => {
            let csv_data = state.storage.export_posts_csv(&req.post_ids).await;
            (
                [
                    (header::CONTENT_TYPE, "text/csv; charset=utf-8".to_string()),
                    (
                        header::CONTENT_DISPOSITION,
                        format!(
                            "attachment; filename=facebook_posts_{}.csv",
                            req.post_ids.len()
                        ),
                    ),
                ],
                csv_data,
            )
                .into_response()
        }
        "crawl_comments" => {
            let task_id = format!("bulk_comments_{}", Uuid::new_v4().simple());
            let total = req.post_ids.len();
            state.crawler.bulk_progress.insert(
                task_id.clone(),
                json!({
                    "status": "running",
                    "current": 0,
                    "total": total,
                    "message": "Đang khởi tạo..."
                }),
            );
            let crawler = state.crawler.clone();
            let post_ids = req.post_ids.clone();
            let cookie = req.cookie.clone();
            let tid = task_id.clone();
            tokio::spawn(async move {
                if let Some(c) = cookie.filter(|s| !s.is_empty()) {
                    let mut entry = crawler.tenant_auth.entry(client_id.clone()).or_default();
                    entry.cookie = c;
                }
                for (idx, pid) in post_ids.iter().enumerate() {
                    crawler.bulk_progress.insert(
                        tid.clone(),
                        json!({
                            "status": "running",
                            "current": idx + 1,
                            "total": total,
                            "message": format!("Đang cào bình luận bài {}/{}...", idx + 1, total)
                        }),
                    );
                    crawler
                        .run_single_comment_crawl(pid, None, &client_id)
                        .await;
                    tokio::time::sleep(Duration::from_millis(800)).await;
                }
                crawler.bulk_progress.insert(
                    tid,
                    json!({
                        "status": "done",
                        "current": total,
                        "total": total,
                        "message": format!("Hoàn tất cào bình luận {} bài!", total)
                    }),
                );
            });
            Json(json!({ "status": "ok", "task_id": task_id })).into_response()
        }
        "check_status" | "refresh" => {
            let task_id = format!("bulk_{}_{}", req.action, Uuid::new_v4().simple());
            let total = req.post_ids.len();
            state
                .storage
                .update_post_status(&req.post_ids, Some(true))
                .await;
            state.crawler.bulk_progress.insert(
                task_id.clone(),
                json!({
                    "status": "done",
                    "current": total,
                    "total": total,
                    "message": format!("Hoàn tất xử lý {} bài viết!", total)
                }),
            );
            Json(json!({ "status": "ok", "task_id": task_id })).into_response()
        }
        other => (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "message": format!("Unknown action: {}", other) })),
        )
            .into_response(),
    }
}

async fn handle_bulk_status(
    State(state): State<FacebookRouteState>,
    Query(q): Query<TaskIdQuery>,
) -> Json<Value> {
    let tid = q.task_id.unwrap_or_default();
    let progress = state
        .crawler
        .bulk_progress
        .get(&tid)
        .map(|v| v.value().clone())
        .unwrap_or_else(
            || json!({ "status": "done", "current": 1, "total": 1, "message": "Hoàn tất" }),
        );
    Json(json!({ "status": "ok", "progress": progress }))
}

async fn handle_fb_crawl_stop(State(state): State<FacebookRouteState>) -> Json<Value> {
    state.crawler.stop();
    Json(json!({
        "status": "ok",
        "message": "Đã gửi lệnh dừng thu thập dữ liệu."
    }))
}

async fn handle_fb_crawl_status(State(state): State<FacebookRouteState>) -> Json<Value> {
    Json(state.crawler.get_status())
}

async fn handle_bridge_status(State(state): State<FacebookRouteState>) -> Json<Value> {
    Json(state.bridge.get_status())
}

async fn handle_bridge_jobs(
    State(state): State<FacebookRouteState>,
    headers: HeaderMap,
    Query(q): Query<ClientIdQuery>,
) -> Json<Value> {
    let client_id = q
        .client_id
        .or_else(|| {
            headers
                .get("x-client-id")
                .or_else(|| headers.get("x-bridge-client-id"))
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        })
        .unwrap_or_else(|| "default".to_string());

    let ua = headers
        .get(header::USER_AGENT)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("ChromeExtension");

    state.bridge.record_heartbeat(&client_id, ua);
    let job = state.bridge.pop_job(&client_id);
    let jobs = match &job {
        Some(j) => vec![j.clone()],
        None => Vec::new(),
    };
    Json(json!({
        "job": job,
        "jobs": jobs,
    }))
}

async fn handle_bridge_result(
    State(state): State<FacebookRouteState>,
    Json(payload): Json<BridgeResultPayload>,
) -> Json<Value> {
    let accepted = state.bridge.submit_result(payload);
    Json(json!({ "status": "ok", "accepted": accepted }))
}
