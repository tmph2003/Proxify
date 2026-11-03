use async_trait::async_trait;
use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use base64::Engine;
use dashmap::DashMap;
use flate2::read::GzDecoder;
use proxify_sdk::{
    BaseExtension, EventPublisher, ExtensionContext, HttpFlow, MutatorInterceptor, UiPageMetadata,
};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;
use tracing::info;

pub mod storage;
pub use storage::ZaloStorage;

pub struct ZaloExtractor {
    storage: Arc<ZaloStorage>,
    event_bus: Arc<dyn EventPublisher>,
}

impl ZaloExtractor {
    pub fn new(storage: Arc<ZaloStorage>, event_bus: Arc<dyn EventPublisher>) -> Arc<Self> {
        Arc::new(Self { storage, event_bus })
    }

    pub async fn process_capture(&self, record: &Value) -> Value {
        let mut parsed = self.extract_json_from_capture(record);
        if parsed.is_empty() {
            return json!({ "groups": 0, "users": 0, "memberships": 0 });
        }

        let mut groups = Vec::new();
        let mut users = Vec::new();
        let mut memberships = Vec::new();

        for obj in &mut parsed {
            self.walk_and_extract(obj, &mut groups, &mut users, &mut memberships, 0);
        }

        let g_cnt = self.storage.upsert_groups(&groups).await;
        let u_cnt = self.storage.upsert_users(&users).await;
        let m_cnt = self.storage.upsert_group_members(&memberships).await;

        if g_cnt > 0 || u_cnt > 0 || m_cnt > 0 {
            self.event_bus.broadcast_ws(
                "zalo_entity_updated",
                json!({
                    "groups_upserted": g_cnt,
                    "users_upserted": u_cnt,
                    "memberships_upserted": m_cnt,
                }),
            );
        }

        json!({
            "groups": g_cnt,
            "users": u_cnt,
            "memberships": m_cnt,
        })
    }

    fn extract_json_from_capture(&self, record: &Value) -> Vec<Value> {
        let mut results = Vec::new();
        let hook_type = record.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let data = match record.get("data") {
            Some(d) => d,
            None => return results,
        };

        if hook_type == "JSON.parse" {
            if let Some(obj_val) = data.get("object") {
                if obj_val.is_object() || obj_val.is_array() {
                    results.push(obj_val.clone());
                } else if let Some(s) = obj_val.as_str() {
                    if let Ok(v) = serde_json::from_str::<Value>(s) {
                        results.push(v);
                    }
                }
            }
            return results;
        }

        if let Some(hex_str) = data
            .get("plaintext_hex")
            .and_then(|v| v.as_str())
            .or_else(|| data.get("result_hex").and_then(|v| v.as_str()))
        {
            if let Ok(raw) = hex::decode(hex_str) {
                self.try_decode_bytes(&raw, &mut results);
            }
        }

        if let Some(b64_str) = data
            .get("plaintext_base64")
            .and_then(|v| v.as_str())
            .or_else(|| data.get("result_base64").and_then(|v| v.as_str()))
        {
            if let Ok(raw) = base64::engine::general_purpose::STANDARD.decode(b64_str) {
                self.try_decode_bytes(&raw, &mut results);
            }
        }

        if let Some(txt) = data.get("plaintext_utf8").and_then(|v| v.as_str()) {
            if let Ok(v) = serde_json::from_str::<Value>(txt) {
                results.push(v);
            }
        }

        results
    }

    fn try_decode_bytes(&self, raw: &[u8], results: &mut Vec<Value>) {
        if raw.len() >= 2 && raw[0] == 0x1f && raw[1] == 0x8b {
            let mut decoder = GzDecoder::new(raw);
            let mut decompressed = Vec::new();
            if decoder.read_to_end(&mut decompressed).is_ok() {
                if let Ok(s) = std::str::from_utf8(&decompressed) {
                    if let Ok(v) = serde_json::from_str::<Value>(s) {
                        results.push(v);
                        return;
                    }
                }
            }
        }
        if let Ok(s) = std::str::from_utf8(raw) {
            if let Ok(v) = serde_json::from_str::<Value>(s) {
                results.push(v);
            }
        }
    }

    fn walk_and_extract(
        &self,
        node: &Value,
        groups: &mut Vec<Value>,
        users: &mut Vec<Value>,
        memberships: &mut Vec<Value>,
        depth: usize,
    ) {
        if depth > 12 {
            return;
        }
        match node {
            Value::Object(map) => {
                if let Some(grid_map) = map.get("gridInfoMap").and_then(|v| v.as_object()) {
                    for (gid, ginfo) in grid_map {
                        if let Some(g_obj) = ginfo.as_object() {
                            self.extract_single_group(gid, g_obj, groups, users, memberships);
                        }
                    }
                }

                if let Some(gid) = map
                    .get("groupId")
                    .or_else(|| map.get("grid"))
                    .and_then(|v| v.as_str())
                {
                    if map.contains_key("name")
                        && (map.contains_key("totalMember")
                            || map.contains_key("memberIds")
                            || map.contains_key("memVerList"))
                    {
                        self.extract_single_group(gid, map, groups, users, memberships);
                    }
                }

                if let Some(uid) = map
                    .get("userId")
                    .or_else(|| map.get("uid"))
                    .and_then(|v| v.as_str())
                {
                    if map.contains_key("displayName")
                        || map.contains_key("zaloName")
                        || map.contains_key("dName")
                    {
                        self.extract_single_user(uid, map, users);
                    }
                }

                for (_, val) in map {
                    self.walk_and_extract(val, groups, users, memberships, depth + 1);
                }
            }
            Value::Array(arr) => {
                for item in arr {
                    self.walk_and_extract(item, groups, users, memberships, depth + 1);
                }
            }
            _ => {}
        }
    }

    fn extract_single_group(
        &self,
        gid: &str,
        g_obj: &serde_json::Map<String, Value>,
        groups: &mut Vec<Value>,
        users: &mut Vec<Value>,
        memberships: &mut Vec<Value>,
    ) {
        let name = g_obj
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown Group");
        let avatar = g_obj
            .get("avt")
            .or_else(|| g_obj.get("fullAvt"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let total_member = g_obj
            .get("totalMember")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let creator_id = g_obj
            .get("creatorId")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let admin_ids = g_obj.get("adminIds").cloned().unwrap_or_else(|| json!([]));

        let mut invite_link = String::new();
        if let Some(other) = g_obj.get("otherInfo").and_then(|v| v.as_object()) {
            if let Some(l) = other.get("link").and_then(|v| v.as_str()) {
                invite_link = l.to_string();
            }
        }

        groups.push(json!({
            "group_id": gid,
            "name": name,
            "avatar": avatar,
            "total_member": total_member,
            "creator_id": creator_id,
            "admin_ids": admin_ids,
            "invite_link": invite_link,
            "raw_json": Value::Object(g_obj.clone()),
        }));

        let admin_set: Vec<String> = admin_ids
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        if !creator_id.is_empty() {
            memberships.push(json!({
                "group_id": gid,
                "user_id": creator_id,
                "role": "CREATOR",
            }));
        }

        for aid in &admin_set {
            let role = if aid == creator_id {
                "CREATOR"
            } else {
                "ADMIN"
            };
            memberships.push(json!({
                "group_id": gid,
                "user_id": aid,
                "role": role,
            }));
        }

        if let Some(mem_ver) = g_obj.get("memVerList").and_then(|v| v.as_array()) {
            for entry in mem_ver {
                if let Some(s) = entry.as_str() {
                    let uid = s.split('_').next().unwrap_or(s);
                    let role = if uid == creator_id {
                        "CREATOR"
                    } else if admin_set.iter().any(|a| a == uid) {
                        "ADMIN"
                    } else {
                        "MEMBER"
                    };
                    memberships.push(json!({
                        "group_id": gid,
                        "user_id": uid,
                        "role": role,
                    }));
                }
            }
        }

        if let Some(current_mems) = g_obj.get("currentMems").and_then(|v| v.as_array()) {
            for m in current_mems {
                if let Some(m_obj) = m.as_object() {
                    if let Some(uid) = m_obj
                        .get("id")
                        .or_else(|| m_obj.get("userId"))
                        .and_then(|v| v.as_str())
                    {
                        self.extract_single_user(uid, m_obj, users);
                        let role = if uid == creator_id {
                            "CREATOR"
                        } else if admin_set.iter().any(|a| a == uid) {
                            "ADMIN"
                        } else {
                            "MEMBER"
                        };
                        memberships.push(json!({
                            "group_id": gid,
                            "user_id": uid,
                            "role": role,
                        }));
                    }
                }
            }
        }
    }

    fn extract_single_user(
        &self,
        uid: &str,
        u_obj: &serde_json::Map<String, Value>,
        users: &mut Vec<Value>,
    ) {
        let clean_uid = uid.split('_').next().unwrap_or(uid);
        let display_name = u_obj
            .get("displayName")
            .or_else(|| u_obj.get("dName"))
            .or_else(|| u_obj.get("zaloName"))
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown");
        let zalo_name = u_obj.get("zaloName").and_then(|v| v.as_str()).unwrap_or("");
        let avatar = u_obj
            .get("avatar")
            .or_else(|| u_obj.get("avt"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let account_status = u_obj
            .get("accountStatus")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let gender = u_obj.get("gender").and_then(|v| v.as_i64());
        let dob = u_obj.get("dob").and_then(|v| v.as_i64());
        let phone = u_obj
            .get("phoneNumber")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let global_id = u_obj.get("globalId").and_then(|v| v.as_str()).unwrap_or("");

        users.push(json!({
            "user_id": clean_uid,
            "display_name": display_name,
            "zalo_name": zalo_name,
            "avatar": avatar,
            "account_status": account_status,
            "gender": gender,
            "dob": dob,
            "phone_number": phone,
            "global_id": global_id,
            "raw_json": Value::Object(u_obj.clone()),
        }));
    }
}

pub struct ZaloHookMutator {
    combined_hooks_js: String,
    wasm_bridge_js: String,
}

impl ZaloHookMutator {
    pub fn load_hooks(ext_dir: &Path) -> Arc<Self> {
        let hooks_dir = ext_dir.join("hooks");
        let mut combined = String::new();
        for file in [
            "crypto_subtle.js",
            "json_parse.js",
            "wasm_instantiate.js",
            "wasm_exports_wrapper.js",
        ] {
            let p = hooks_dir.join(file);
            if let Ok(content) = std::fs::read_to_string(&p) {
                combined.push_str("\n// --- ");
                combined.push_str(file);
                combined.push_str(" ---\n");
                combined.push_str(&content);
            }
        }
        let wasm_bridge_js =
            std::fs::read_to_string(hooks_dir.join("trusted-device-bridge.js")).unwrap_or_default();

        Arc::new(Self {
            combined_hooks_js: combined,
            wasm_bridge_js,
        })
    }
}

#[async_trait]
impl MutatorInterceptor for ZaloHookMutator {
    async fn mutate_request(&self, _flow: &mut HttpFlow) {}

    async fn mutate_response(&self, flow: &mut HttpFlow) {
        let host = flow.request.host.to_lowercase();
        if !host.contains("zalo.me") {
            return;
        }
        let path = flow.request.path.clone();
        let ct = flow.response_content_type();
        let resp = match flow.response.as_mut() {
            Some(r) => r,
            None => return,
        };

        if path.contains("trusted-device-bridge")
            && path.ends_with(".js")
            && !self.wasm_bridge_js.is_empty()
        {
            resp.content = self.wasm_bridge_js.as_bytes().to_vec().into();
            return;
        }

        if ct.contains("text/html") && !self.combined_hooks_js.is_empty() {
            let mut csp_keys = Vec::new();
            for k in resp.headers.keys() {
                if k.eq_ignore_ascii_case("content-security-policy")
                    || k.eq_ignore_ascii_case("content-security-policy-report-only")
                {
                    csp_keys.push(k.clone());
                }
            }
            for k in csp_keys {
                resp.headers.remove(&k);
            }

            if let Ok(html) = std::str::from_utf8(&resp.content) {
                if !html.contains("id=\"proxify-zalo-hooks\"") {
                    let script_tag = format!(
                        "<script id=\"proxify-zalo-hooks\">\n{}\n</script>",
                        self.combined_hooks_js
                    );
                    let modified = if let Some(pos) = html.find("<head>") {
                        let mut s = html.to_string();
                        s.insert_str(pos + 6, &script_tag);
                        s
                    } else {
                        format!("{}{}", script_tag, html)
                    };
                    resp.content = modified.into_bytes().into();
                }
            }
        }
    }
}

#[derive(Clone)]
struct ZaloRouteState {
    storage: Arc<ZaloStorage>,
    extractor: Arc<ZaloExtractor>,
    dedup_cache: Arc<DashMap<String, Instant>>,
    pending_commands: Arc<parking_lot::Mutex<Vec<Value>>>,
    ext_dir: PathBuf,
}

#[derive(Deserialize)]
struct ZaloListQuery {
    search: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
    group_id: Option<String>,
    format: Option<String>,
}

#[derive(Deserialize)]
struct ZaloScanRequest {
    link: Option<String>,
    group_id: Option<String>,
}

pub struct ZaloExtension {
    ext_dir: PathBuf,
}

impl ZaloExtension {
    pub fn new(ext_dir: PathBuf) -> Self {
        Self { ext_dir }
    }
}

#[async_trait]
impl BaseExtension for ZaloExtension {
    fn name(&self) -> &str {
        "zalo"
    }

    async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        let storage = ZaloStorage::new(context.db_pool().clone());
        storage.init_schema().await?;

        let extractor = ZaloExtractor::new(storage.clone(), context.event_bus());
        let mutator = ZaloHookMutator::load_hooks(&self.ext_dir);

        context.register_mutator("*.zalo.me", mutator.clone());
        context.register_mutator("chat.zalo.me", mutator);

        for stream_domain in ["*.zadn.vn", "*.zdn.vn"] {
            context.register_stream_rule(stream_domain);
        }

        context.register_stream_exclusion("*.zalo.me", "trusted-device-bridge");
        context.register_stream_exclusion("zalo.me", "trusted-device-bridge");
        context.register_stream_exclusion("chat.zalo.me", "trusted-device-bridge");

        let state = ZaloRouteState {
            storage,
            extractor,
            dedup_cache: Arc::new(DashMap::new()),
            pending_commands: Arc::new(parking_lot::Mutex::new(Vec::new())),
            ext_dir: self.ext_dir.clone(),
        };

        let router = Router::new()
            .route("/zalo", get(handle_zalo_ui))
            .route("/api/zalo/static/:file", get(handle_zalo_static))
            .route("/api/capture_dump", post(handle_capture_dump))
            .route("/api/zalo/stats", get(handle_zalo_stats))
            .route("/api/zalo/groups", get(handle_zalo_groups))
            .route("/api/zalo/groups/:id", get(handle_zalo_group_detail))
            .route(
                "/api/zalo/groups/:id/members",
                get(handle_zalo_group_members),
            )
            .route("/api/zalo/groups/:id/export", get(handle_zalo_group_export))
            .route(
                "/api/zalo/members/export/:format",
                get(handle_zalo_members_export),
            )
            .route("/api/zalo/users", get(handle_zalo_users))
            .route("/api/zalo/jobs", get(handle_zalo_jobs))
            .route("/api/zalo/jobs/:id/cancel", post(handle_zalo_cancel_job))
            .route("/api/zalo/scan", post(handle_zalo_scan))
            .route(
                "/api/zalo/commands/pending",
                get(handle_zalo_pending_commands),
            )
            .route(
                "/api/zalo/commands/fetch_members",
                post(handle_zalo_fetch_members_cmd),
            )
            .with_state(state);

        context.register_sub_router(router);
        context.register_ui_page(UiPageMetadata {
            name: "zalo".to_string(),
            path: "/zalo".to_string(),
            title: "Zalo Extractor".to_string(),
            icon: "💬".to_string(),
            description: "Zalo Web Decryption, Group & Member Intelligence".to_string(),
            order: 30,
        });

        info!("[Extension: Zalo] Initialized routes, JS hooks & PostgreSQL schema.");
        Ok(())
    }
}

async fn handle_zalo_ui(State(state): State<ZaloRouteState>) -> Response {
    let html_path = state.ext_dir.join("static").join("zalo.html");
    match tokio::fs::read_to_string(&html_path).await {
        Ok(html) => Html(html).into_response(),
        Err(_) => Html("<h1>Zalo Command Center</h1>".to_string()).into_response(),
    }
}

async fn handle_zalo_static(
    State(state): State<ZaloRouteState>,
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

async fn handle_capture_dump(
    State(state): State<ZaloRouteState>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let raw_str = serde_json::to_string(&payload).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(raw_str.as_bytes());
    let digest = hex::encode(hasher.finalize());

    let now = Instant::now();
    if state.dedup_cache.len() > 2000 {
        state
            .dedup_cache
            .retain(|_, ts| now.duration_since(*ts).as_secs() < 10);
    }
    if let Some(prev) = state.dedup_cache.get(&digest) {
        if now.duration_since(*prev).as_secs() < 5 {
            return Json(json!({ "status": "dedup_skipped" }));
        }
    }
    state.dedup_cache.insert(digest, now);

    let extracted = state.extractor.process_capture(&payload).await;
    Json(json!({
        "status": "ok",
        "extracted": extracted,
    }))
}

async fn handle_zalo_stats(State(state): State<ZaloRouteState>) -> Json<Value> {
    Json(state.storage.get_stats().await)
}

async fn handle_zalo_groups(
    State(state): State<ZaloRouteState>,
    Query(q): Query<ZaloListQuery>,
) -> Json<Value> {
    let limit = q.limit.unwrap_or(50).clamp(1, 500);
    let offset = q.offset.unwrap_or(0).max(0);
    Json(
        state
            .storage
            .get_groups(q.search.as_deref(), limit, offset)
            .await,
    )
}

async fn handle_zalo_group_detail(
    State(state): State<ZaloRouteState>,
    AxumPath(id): AxumPath<String>,
    Query(q): Query<ZaloListQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(100).clamp(1, 1000);
    let offset = q.offset.unwrap_or(0).max(0);
    match state
        .storage
        .get_group_detail(&id, q.search.as_deref(), limit, offset)
        .await
    {
        Some(detail) => Json(detail).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "Group not found" })),
        )
            .into_response(),
    }
}

async fn handle_zalo_users(
    State(state): State<ZaloRouteState>,
    Query(q): Query<ZaloListQuery>,
) -> Json<Value> {
    let limit = q.limit.unwrap_or(50).clamp(1, 500);
    let offset = q.offset.unwrap_or(0).max(0);
    Json(
        state
            .storage
            .get_users(q.search.as_deref(), limit, offset)
            .await,
    )
}

async fn handle_zalo_group_members(
    State(state): State<ZaloRouteState>,
    AxumPath(id): AxumPath<String>,
    Query(q): Query<ZaloListQuery>,
) -> Json<Value> {
    let limit = q.limit.unwrap_or(500).clamp(1, 5000);
    let offset = q.offset.unwrap_or(0).max(0);
    let members = state
        .storage
        .get_group_members(&id, q.search.as_deref(), limit, offset)
        .await;
    Json(Value::Array(members))
}

async fn handle_zalo_group_export(
    State(state): State<ZaloRouteState>,
    AxumPath(id): AxumPath<String>,
    Query(q): Query<ZaloListQuery>,
) -> Response {
    let fmt = q.format.as_deref().unwrap_or("csv");
    export_group_members_response(&state, &id, fmt).await
}

async fn handle_zalo_members_export(
    State(state): State<ZaloRouteState>,
    AxumPath(format): AxumPath<String>,
    Query(q): Query<ZaloListQuery>,
) -> Response {
    let gid = q.group_id.unwrap_or_default();
    export_group_members_response(&state, &gid, &format).await
}

async fn export_group_members_response(
    state: &ZaloRouteState,
    group_id: &str,
    fmt: &str,
) -> Response {
    if fmt.eq_ignore_ascii_case("csv") {
        let csv_data = state.storage.export_members_csv(group_id).await;
        (
            [
                (header::CONTENT_TYPE, "text/csv; charset=utf-8".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=zalo_group_{}.csv", group_id),
                ),
            ],
            csv_data,
        )
            .into_response()
    } else {
        let members = state
            .storage
            .get_group_members(group_id, None, 100_000, 0)
            .await;
        let json_str = serde_json::to_string_pretty(&members).unwrap_or_else(|_| "[]".to_string());
        (
            [
                (
                    header::CONTENT_TYPE,
                    "application/json; charset=utf-8".to_string(),
                ),
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=zalo_group_{}.json", group_id),
                ),
            ],
            json_str,
        )
            .into_response()
    }
}

async fn handle_zalo_jobs(State(state): State<ZaloRouteState>) -> Json<Value> {
    let jobs = state.storage.get_jobs(50).await;
    Json(Value::Array(jobs))
}

async fn handle_zalo_cancel_job(
    State(state): State<ZaloRouteState>,
    AxumPath(id): AxumPath<i32>,
) -> Json<Value> {
    state.storage.cancel_job(id).await;
    Json(json!({ "status": "ok" }))
}

async fn handle_zalo_scan(
    State(state): State<ZaloRouteState>,
    Json(req): Json<ZaloScanRequest>,
) -> Response {
    let link = req.link.unwrap_or_default().trim().to_string();
    let group_id = req.group_id.unwrap_or_default().trim().to_string();

    let job_link = if !group_id.is_empty() {
        format!("group_id:{}", group_id)
    } else if !link.is_empty() {
        link
    } else {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "error": "Link or group_id is required" })),
        )
            .into_response();
    };

    match state.storage.create_job(&job_link, "pending").await {
        Some(job_id) => Json(json!({ "status": "ok", "job_id": job_id })).into_response(),
        None => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({ "status": "error", "error": "Database error" })),
        )
            .into_response(),
    }
}

async fn handle_zalo_pending_commands(State(state): State<ZaloRouteState>) -> Json<Value> {
    let mut cmds = state.pending_commands.lock();
    let list: Vec<Value> = cmds.drain(..).collect();
    Json(Value::Array(list))
}

async fn handle_zalo_fetch_members_cmd(
    State(state): State<ZaloRouteState>,
    Json(req): Json<ZaloScanRequest>,
) -> Response {
    let group_id = req.group_id.unwrap_or_default().trim().to_string();
    if group_id.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "status": "error", "error": "group_id required" })),
        )
            .into_response();
    }

    let job_id = state
        .storage
        .create_job(&format!("Lấy thành viên nhóm {}", group_id), "running")
        .await;

    state.pending_commands.lock().push(json!({
        "action": "fetch_members",
        "group_id": group_id,
    }));

    Json(json!({
        "status": "ok",
        "job_id": job_id,
        "message": format!("Đã gửi lệnh lấy thành viên nhóm {}. Chờ JS hooks xử lý...", group_id)
    }))
    .into_response()
}
