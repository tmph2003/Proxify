use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        DefaultBodyLimit, Path, Query, State,
    },
    http::{header, HeaderMap, Method, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use proxify_sdk::UiPageMetadata;
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::broadcast;
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::ServeDir;

use crate::exporter::RequestExporter;
use crate::storage::{RequestFilter, RequestStorage};

#[derive(Clone)]
pub struct DashboardState {
    pub storage: Arc<RequestStorage>,
    pub ws_tx: broadcast::Sender<String>,
    pub ui_pages: Arc<Vec<UiPageMetadata>>,
    pub frontend_dir: PathBuf,
}

#[derive(Deserialize)]
pub struct ToggleDbPayload {
    pub enabled: Option<bool>,
    pub allowed_domains: Option<Vec<String>>,
}

#[derive(Deserialize)]
pub struct DeleteQuery {
    pub domain: Option<String>,
}

#[derive(Deserialize)]
pub struct ExportQuery {
    pub domain: Option<String>,
    pub method: Option<String>,
    pub status: Option<i32>,
    pub graphql: Option<String>,
    pub ids: Option<String>,
    pub limit: Option<i64>,
}

#[derive(Deserialize)]
pub struct RequestsQuery {
    pub domain: Option<String>,
    pub method: Option<String>,
    pub status: Option<i32>,
    pub status_code: Option<i32>,
    pub content_type: Option<String>,
    pub search: Option<String>,
    pub graphql: Option<String>,
    pub graphql_only: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

pub fn build_dashboard_router(state: DashboardState, extension_routers: Vec<Router>) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::PATCH,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers(Any)
        .expose_headers([header::CONTENT_DISPOSITION]);

    let frontend_dir = state.frontend_dir.clone();

    let mut app = Router::new()
        .route("/", get(handle_index))
        .route("/ws", get(handle_websocket))
        .route(
            "/api/requests",
            get(handle_get_requests).delete(handle_delete_requests),
        )
        .route("/api/requests/:id", get(handle_get_request_detail))
        .route("/api/domains", get(handle_get_domains))
        .route("/api/stats", get(handle_get_stats))
        .route("/api/export/:format", get(handle_export))
        .route("/api/toggle_db", post(handle_toggle_db))
        .route("/api/config", get(handle_get_config))
        .route("/api/health", get(handle_health))
        .route("/api/status", get(handle_health))
        .route("/api/extensions", get(handle_get_extensions))
        .with_state(state);

    for ext_router in extension_routers {
        app = app.merge(ext_router);
    }

    if frontend_dir.exists() {
        app = app.nest_service("/static", ServeDir::new(frontend_dir));
    }

    app.layer(DefaultBodyLimit::max(50 * 1024 * 1024))
        .layer(cors)
}

async fn handle_index(State(state): State<DashboardState>) -> Response {
    let index_path = state.frontend_dir.join("index.html");
    match tokio::fs::read_to_string(&index_path).await {
        Ok(html) => Html(html).into_response(),
        Err(_) => Html(
            "<h1>Proxify Dashboard (Rust Core)</h1><p>Frontend assets not found.</p>".to_string(),
        )
        .into_response(),
    }
}

async fn handle_websocket(
    ws: WebSocketUpgrade,
    State(state): State<DashboardState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| ws_client_loop(socket, state.ws_tx.subscribe()))
}

async fn ws_client_loop(mut socket: WebSocket, mut rx: broadcast::Receiver<String>) {
    loop {
        tokio::select! {
            msg = rx.recv() => {
                match msg {
                    Ok(text) => {
                        if socket.send(Message::Text(text)).await.is_err() {
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
            client_msg = socket.recv() => {
                match client_msg {
                    Some(Ok(Message::Text(txt))) => {
                        if txt == "ping" {
                            let _ = socket.send(Message::Text("pong".to_string())).await;
                        }
                    }
                    Some(Ok(Message::Close(_))) | None | Some(Err(_)) => break,
                    _ => {}
                }
            }
        }
    }
}

async fn handle_get_requests(
    State(state): State<DashboardState>,
    Query(q): Query<RequestsQuery>,
) -> Json<Value> {
    let gql_param = q.graphql.as_deref().or(q.graphql_only.as_deref());
    let is_graphql = match gql_param {
        Some("true") | Some("1") => Some(true),
        Some("false") | Some("0") => Some(false),
        _ => None,
    };
    let filter = RequestFilter {
        domain: q.domain,
        method: q.method,
        status_code: q.status.or(q.status_code),
        content_type: q.content_type,
        search: q.search,
        is_graphql,
        limit: q.limit,
        offset: q.offset,
    };
    Json(state.storage.query_requests(&filter).await)
}

async fn handle_get_request_detail(
    State(state): State<DashboardState>,
    Path(id): Path<i64>,
) -> Response {
    match state.storage.get_request(id).await {
        Some(detail) => Json(detail).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "Request not found" })),
        )
            .into_response(),
    }
}

async fn handle_get_domains(State(state): State<DashboardState>) -> Json<Value> {
    let domains = state.storage.get_domains().await;
    Json(Value::Array(domains))
}

async fn handle_get_stats(State(state): State<DashboardState>) -> Json<Value> {
    let mut stats = state.storage.get_stats().await;
    if let Some(obj) = stats.as_object_mut() {
        obj.insert(
            "ws_clients".to_string(),
            json!(state.ws_tx.receiver_count()),
        );
        obj.insert("save_to_db".to_string(), json!(state.storage.is_saving()));
    }
    Json(stats)
}

async fn handle_delete_requests(
    State(state): State<DashboardState>,
    Query(q): Query<DeleteQuery>,
) -> Json<Value> {
    let deleted = state.storage.delete_requests(q.domain.as_deref()).await;
    Json(json!({ "deleted": deleted }))
}

async fn handle_toggle_db(
    State(state): State<DashboardState>,
    Json(payload): Json<ToggleDbPayload>,
) -> Json<Value> {
    let has_domains_update = payload.allowed_domains.is_some();
    if let Some(domains) = payload.allowed_domains {
        state.storage.set_allowed_domains(domains);
    }
    let new_val = match payload.enabled {
        Some(v) => {
            state.storage.set_saving(v);
            v
        }
        None if !has_domains_update => {
            let v = !state.storage.is_saving();
            state.storage.set_saving(v);
            v
        }
        None => state.storage.is_saving(),
    };
    let allowed = state.storage.get_allowed_domains();
    if state.ws_tx.receiver_count() > 0 {
        let _ = state.ws_tx.send(
            json!({
                "type": "config_updated",
                "data": {
                    "save_to_db": new_val,
                    "db_integration_enabled": new_val,
                    "db_allowed_domains": allowed,
                }
            })
            .to_string(),
        );
    }
    Json(json!({
        "status": "ok",
        "save_to_db": new_val,
        "db_integration_enabled": new_val,
        "db_allowed_domains": allowed,
        "retention_days": state.storage.retention_days,
    }))
}

async fn handle_get_config(State(state): State<DashboardState>) -> Json<Value> {
    let saving = state.storage.is_saving();
    Json(json!({
        "save_to_db": saving,
        "db_integration_enabled": saving,
        "db_allowed_domains": state.storage.get_allowed_domains(),
        "max_body_size": state.storage.max_body_size,
        "retention_days": state.storage.retention_days,
        "commit_batch_size": state.storage.commit_batch_size,
    }))
}

async fn handle_health(State(state): State<DashboardState>) -> Json<Value> {
    let saving = state.storage.is_saving();
    Json(json!({
        "status": "ok",
        "engine": "proxify-rust",
        "ws_clients": state.ws_tx.receiver_count(),
        "save_to_db": saving,
        "db_integration_enabled": saving,
    }))
}

async fn handle_get_extensions(State(state): State<DashboardState>) -> Json<Value> {
    let mut pages = (*state.ui_pages).clone();
    pages.sort_by_key(|p| p.order);
    Json(json!({
        "status": "ok",
        "enabled": true,
        "extensions": pages,
    }))
}

async fn handle_export(
    State(state): State<DashboardState>,
    Path(fmt): Path<String>,
    Query(q): Query<ExportQuery>,
) -> Response {
    let fmt_lower = fmt.to_lowercase();
    let is_graphql = match q.graphql.as_deref() {
        Some("true") | Some("1") => Some(true),
        Some("false") | Some("0") => Some(false),
        _ => None,
    };

    let records = if let Some(ref ids_str) = q.ids {
        let mut list = Vec::new();
        for part in ids_str.split(',') {
            if let Ok(id) = part.trim().parse::<i64>() {
                if let Some(r) = state.storage.get_request(id).await {
                    list.push(r);
                }
            }
        }
        list
    } else {
        let filter = RequestFilter {
            domain: q.domain.clone(),
            method: q.method,
            status_code: q.status,
            content_type: None,
            search: None,
            is_graphql,
            limit: Some(q.limit.unwrap_or(500)),
            offset: Some(0),
        };
        state.storage.get_requests_for_export(&filter).await
    };

    if records.is_empty() {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "No matching requests to export" })),
        )
            .into_response();
    }

    let domain_suffix = q
        .domain
        .as_deref()
        .map(|d| format!("_{}", d.replace('.', "_")))
        .unwrap_or_default();

    let (content, content_type, filename) = match fmt_lower.as_str() {
        "json" => (
            RequestExporter::to_json(&records, true),
            "application/json",
            format!("proxify_export{}.json", domain_suffix),
        ),
        "har" => (
            RequestExporter::to_har(&records),
            "application/json",
            format!("proxify_export{}.har", domain_suffix),
        ),
        "python" | "py" => (
            RequestExporter::to_python(&records),
            "text/x-python",
            format!("proxify_requests{}.py", domain_suffix),
        ),
        "curl" | "sh" => (
            RequestExporter::to_curl(&records),
            "text/plain",
            format!("proxify_curl{}.sh", domain_suffix),
        ),
        _ => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({
                    "error": format!("Unsupported format: {}. Use json, har, python, or curl", fmt_lower)
                })),
            )
                .into_response();
        }
    };

    let mut headers = HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        header::HeaderValue::from_str(content_type)
            .unwrap_or(header::HeaderValue::from_static("text/plain")),
    );
    if let Ok(disp) =
        header::HeaderValue::from_str(&format!("attachment; filename=\"{}\"", filename))
    {
        headers.insert(header::CONTENT_DISPOSITION, disp);
    }

    (StatusCode::OK, headers, content).into_response()
}
