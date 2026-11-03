use chrono::{DateTime, Utc};
use deadpool_postgres::{Config, ManagerConfig, Pool, RecyclingMethod, Runtime};
use parking_lot::RwLock;
use proxify_sdk::EventPublisher;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};
use tokio_postgres::NoTls;
use tracing::{error, info};

#[derive(Debug)]
pub enum StorageItem {
    Record(Box<RequestRecord>),
    TrackedRecord(Box<RequestRecord>, String),
    Flush(oneshot::Sender<()>),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestRecord {
    pub id: Option<i32>,
    pub timestamp: f64,
    pub method: String,
    pub url: String,
    pub host: String,
    pub path: String,
    pub status_code: Option<i32>,
    pub request_headers: String,
    pub request_body: Option<bytes::Bytes>,
    pub response_headers: Option<String>,
    pub response_body: Option<bytes::Bytes>,
    pub content_type: Option<String>,
    pub duration_ms: Option<f64>,
    pub is_graphql: i32,
    pub graphql_operation: Option<String>,
    pub graphql_query: Option<String>,
    pub graphql_variables: Option<String>,
    pub size_bytes: i32,
}

#[derive(Debug, Default, Clone, Deserialize)]
pub struct RequestFilter {
    pub domain: Option<String>,
    pub method: Option<String>,
    pub status_code: Option<i32>,
    pub content_type: Option<String>,
    pub search: Option<String>,
    pub is_graphql: Option<bool>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

pub fn create_pg_pool(database_url: &str, max_size: usize) -> Result<Pool, String> {
    let mut cfg = Config::new();
    cfg.url = Some(database_url.to_string());
    cfg.manager = Some(ManagerConfig {
        recycling_method: RecyclingMethod::Fast,
    });
    cfg.pool = Some(deadpool_postgres::PoolConfig::new(max_size));
    cfg.create_pool(Some(Runtime::Tokio1), NoTls)
        .map_err(|e| format!("Failed to create PostgreSQL pool: {}", e))
}

pub async fn init_core_schemas(pool: &Pool) -> Result<(), String> {
    let client = pool
        .get()
        .await
        .map_err(|e| format!("Failed to connect to Postgres: {}", e))?;

    client
        .batch_execute(
            r#"
            CREATE SCHEMA IF NOT EXISTS core;

            CREATE TABLE IF NOT EXISTS core.raw_payloads (
                id BIGSERIAL PRIMARY KEY,
                topic VARCHAR(255) NOT NULL,
                raw_data JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                processed BOOLEAN DEFAULT FALSE
            );

            CREATE INDEX IF NOT EXISTS idx_raw_payloads_processed
            ON core.raw_payloads(processed)
            WHERE processed = FALSE;

            CREATE TABLE IF NOT EXISTS public.requests (
                id SERIAL PRIMARY KEY,
                timestamp TEXT NOT NULL,
                timestamp_epoch DOUBLE PRECISION NOT NULL,
                method TEXT NOT NULL,
                url TEXT NOT NULL,
                scheme TEXT,
                domain TEXT NOT NULL,
                port INTEGER,
                path TEXT,
                query_string TEXT,
                request_headers TEXT,
                request_body TEXT,
                request_content_type TEXT,
                status_code INTEGER,
                response_headers TEXT,
                response_body TEXT,
                response_content_type TEXT,
                response_size INTEGER DEFAULT 0,
                duration_ms DOUBLE PRECISION,
                is_graphql INTEGER DEFAULT 0,
                graphql_operation TEXT,
                graphql_doc_id TEXT,
                graphql_variables TEXT,
                tags TEXT DEFAULT '[]',
                search_vector tsvector
            );

            CREATE INDEX IF NOT EXISTS idx_requests_domain ON public.requests(domain);
            CREATE INDEX IF NOT EXISTS idx_requests_method ON public.requests(method);
            CREATE INDEX IF NOT EXISTS idx_requests_status ON public.requests(status_code);
            CREATE INDEX IF NOT EXISTS idx_requests_graphql ON public.requests(is_graphql);
            CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON public.requests(timestamp_epoch);
            CREATE INDEX IF NOT EXISTS idx_requests_search ON public.requests USING GIN(search_vector);
            "#,
        )
        .await
        .map_err(|e| format!("Failed to initialize core schemas: {}", e))?;

    info!("[Storage] Core & Public PostgreSQL schemas initialized successfully.");
    Ok(())
}

pub struct RequestStorage {
    pool: Pool,
    tx: mpsc::Sender<StorageItem>,
    pub save_to_db: AtomicBool,
    pub allowed_domains: RwLock<Vec<String>>,
    pub max_body_size: usize,
    pub retention_days: i32,
    pub commit_batch_size: usize,
}

impl RequestStorage {
    pub fn new(pool: Pool) -> Arc<Self> {
        Self::with_event_bus(pool, None)
    }

    pub fn with_event_bus(pool: Pool, event_bus: Option<Arc<dyn EventPublisher>>) -> Arc<Self> {
        let save_to_db = std::env::var("SAVE_TO_DB")
            .or_else(|_| std::env::var("DB_INTEGRATION_ENABLED"))
            .unwrap_or_else(|_| "true".to_string())
            .to_lowercase()
            == "true";
        let max_body_size = std::env::var("MAX_BODY_SIZE")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(5_242_880);
        let retention_days = std::env::var("RECORD_RETENTION_DAYS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(7);
        let commit_batch_size = std::env::var("COMMIT_BATCH_SIZE")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(50);

        let (tx, mut rx) = mpsc::channel::<StorageItem>(2000);
        let pool_writer = pool.clone();
        let batch_limit = commit_batch_size;

        tokio::spawn(async move {
            let mut batch: Vec<(RequestRecord, Option<String>)> = Vec::with_capacity(batch_limit);
            let mut interval = tokio::time::interval(Duration::from_secs(1));

            loop {
                tokio::select! {
                    maybe_item = rx.recv() => {
                        match maybe_item {
                            Some(StorageItem::Record(rec)) => {
                                batch.push((*rec, None));
                                while batch.len() < batch_limit {
                                    match rx.try_recv() {
                                        Ok(StorageItem::Record(next)) => batch.push((*next, None)),
                                        Ok(StorageItem::TrackedRecord(next, uuid)) => batch.push((*next, Some(uuid))),
                                        Ok(StorageItem::Flush(ack)) => {
                                            Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                                            let _ = ack.send(());
                                        }
                                        Err(_) => break,
                                    }
                                }
                                Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                            }
                            Some(StorageItem::TrackedRecord(rec, uuid)) => {
                                batch.push((*rec, Some(uuid)));
                                while batch.len() < batch_limit {
                                    match rx.try_recv() {
                                        Ok(StorageItem::Record(next)) => batch.push((*next, None)),
                                        Ok(StorageItem::TrackedRecord(next, next_uuid)) => batch.push((*next, Some(next_uuid))),
                                        Ok(StorageItem::Flush(ack)) => {
                                            Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                                            let _ = ack.send(());
                                        }
                                        Err(_) => break,
                                    }
                                }
                                Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                            }
                            Some(StorageItem::Flush(ack)) => {
                                while let Ok(item) = rx.try_recv() {
                                    match item {
                                        StorageItem::Record(rec) => batch.push((*rec, None)),
                                        StorageItem::TrackedRecord(rec, uuid) => batch.push((*rec, Some(uuid))),
                                        StorageItem::Flush(other_ack) => {
                                            Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                                            let _ = other_ack.send(());
                                        }
                                    }
                                }
                                Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                                let _ = ack.send(());
                            }
                            None => {
                                if !batch.is_empty() {
                                    Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = interval.tick() => {
                        if !batch.is_empty() {
                            Self::flush_batch(&pool_writer, &mut batch, event_bus.as_ref()).await;
                        }
                    }
                }
            }
        });

        if retention_days > 0 {
            let pool_ttl = pool.clone();
            tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(3600));
                loop {
                    interval.tick().await;
                    let cutoff = (Utc::now().timestamp_millis() as f64 / 1000.0)
                        - (retention_days as f64 * 86400.0);
                    if let Ok(client) = pool_ttl.get().await {
                        if let Ok(deleted) = client
                            .execute(
                                "DELETE FROM public.requests WHERE timestamp_epoch < $1",
                                &[&cutoff],
                            )
                            .await
                        {
                            if deleted > 0 {
                                info!(
                                    "[TTL Worker] Deleted {} expired request records older than {} days.",
                                    deleted, retention_days
                                );
                            }
                        }
                    }
                }
            });
        }

        Arc::new(Self {
            pool,
            tx,
            save_to_db: AtomicBool::new(save_to_db),
            allowed_domains: RwLock::new(Vec::new()),
            max_body_size,
            retention_days,
            commit_batch_size,
        })
    }

    pub fn is_saving(&self) -> bool {
        self.save_to_db.load(Ordering::Relaxed)
    }

    pub fn set_saving(&self, enabled: bool) {
        self.save_to_db.store(enabled, Ordering::Relaxed);
    }

    pub fn get_allowed_domains(&self) -> Vec<String> {
        self.allowed_domains.read().clone()
    }

    pub fn set_allowed_domains(&self, domains: Vec<String>) {
        let cleaned: Vec<String> = domains
            .into_iter()
            .map(|d| d.trim().trim_start_matches("*.").to_lowercase())
            .filter(|d| !d.is_empty())
            .collect();
        *self.allowed_domains.write() = cleaned;
    }

    pub fn should_save_domain(&self, host: &str) -> bool {
        if !self.is_saving() {
            return false;
        }
        let allowed = self.allowed_domains.read();
        if allowed.is_empty() {
            return true;
        }
        let clean_host = host.split(':').next().unwrap_or(host).trim().to_lowercase();
        allowed
            .iter()
            .any(|d| clean_host == *d || clean_host.ends_with(&format!(".{}", d)))
    }

    pub fn enqueue(&self, record: RequestRecord) {
        self.enqueue_internal(record, None);
    }

    pub fn enqueue_tracked(&self, record: RequestRecord, req_uuid: String) {
        self.enqueue_internal(record, Some(req_uuid));
    }

    fn enqueue_internal(&self, mut record: RequestRecord, req_uuid: Option<String>) {
        if !self.should_save_domain(&record.host) {
            return;
        }
        if let Some(ref mut b) = record.request_body {
            if b.len() > self.max_body_size {
                *b = b.slice(0..self.max_body_size);
            }
        }
        if let Some(ref mut b) = record.response_body {
            if b.len() > self.max_body_size {
                *b = b.slice(0..self.max_body_size);
            }
        }
        let item = match req_uuid {
            Some(uuid) if !uuid.is_empty() => StorageItem::TrackedRecord(Box::new(record), uuid),
            _ => StorageItem::Record(Box::new(record)),
        };
        let _ = self.tx.try_send(item);
    }

    pub async fn flush(&self) {
        let (ack_tx, ack_rx) = oneshot::channel();
        if self.tx.send(StorageItem::Flush(ack_tx)).await.is_ok() {
            let _ = ack_rx.await;
        }
    }

    pub async fn shutdown(&self) {
        info!("[Storage] Flushing pending storage queue for shutdown...");
        self.flush().await;
        info!("[Storage] Graceful shutdown flush complete.");
    }

    async fn flush_batch(
        pool: &Pool,
        batch: &mut Vec<(RequestRecord, Option<String>)>,
        event_bus: Option<&Arc<dyn EventPublisher>>,
    ) {
        if batch.is_empty() {
            return;
        }
        let records = std::mem::take(batch);
        let mut client = match pool.get().await {
            Ok(c) => c,
            Err(e) => {
                error!("[Storage] DB connection error during flush: {}", e);
                return;
            }
        };

        let tx = match client.transaction().await {
            Ok(t) => t,
            Err(e) => {
                error!("[Storage] Failed to begin transaction for flush: {}", e);
                return;
            }
        };

        let num_records = records.len();
        let mut sql = String::with_capacity(320 + num_records * 90);
        sql.push_str(
            "INSERT INTO public.requests (
                timestamp, timestamp_epoch, method, url, domain, path, status_code,
                request_headers, request_body, response_headers, response_body,
                response_content_type, duration_ms, is_graphql, graphql_operation,
                graphql_doc_id, graphql_variables, response_size
            ) VALUES ",
        );

        struct RowData {
            req_uuid: Option<String>,
            dt: String,
            timestamp: f64,
            method: String,
            url: String,
            host: String,
            path: String,
            status_code: Option<i32>,
            request_headers: String,
            req_body_str: Option<String>,
            response_headers: Option<String>,
            resp_body_str: Option<String>,
            content_type: Option<String>,
            duration_ms: Option<f64>,
            is_graphql: i32,
            graphql_operation: Option<String>,
            graphql_query: Option<String>,
            graphql_variables: Option<String>,
            size_bytes: i32,
        }

        let mut row_data = Vec::with_capacity(num_records);
        for (r, req_uuid) in records {
            let dt = DateTime::<Utc>::from_timestamp_millis((r.timestamp * 1000.0) as i64)
                .map(|d| d.to_rfc3339())
                .unwrap_or_default();
            let req_body_str = r
                .request_body
                .as_ref()
                .map(|b| String::from_utf8_lossy(b).replace('\0', ""));
            let resp_body_str = r
                .response_body
                .as_ref()
                .map(|b| String::from_utf8_lossy(b).replace('\0', ""));

            row_data.push(RowData {
                req_uuid,
                dt,
                timestamp: r.timestamp,
                method: r.method,
                url: r.url,
                host: r.host,
                path: r.path,
                status_code: r.status_code,
                request_headers: r.request_headers,
                req_body_str,
                response_headers: r.response_headers,
                resp_body_str,
                content_type: r.content_type,
                duration_ms: r.duration_ms,
                is_graphql: r.is_graphql,
                graphql_operation: r.graphql_operation,
                graphql_query: r.graphql_query,
                graphql_variables: r.graphql_variables,
                size_bytes: r.size_bytes,
            });
        }

        use std::fmt::Write;
        for i in 0..num_records {
            if i > 0 {
                sql.push_str(", ");
            }
            let base = i * 18;
            let _ = write!(
                sql,
                "(${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${}, ${})",
                base + 1, base + 2, base + 3, base + 4, base + 5, base + 6,
                base + 7, base + 8, base + 9, base + 10, base + 11, base + 12,
                base + 13, base + 14, base + 15, base + 16, base + 17, base + 18
            );
        }
        sql.push_str(" RETURNING id");

        let mut params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> =
            Vec::with_capacity(num_records * 18);
        for row in &row_data {
            params.push(&row.dt);
            params.push(&row.timestamp);
            params.push(&row.method);
            params.push(&row.url);
            params.push(&row.host);
            params.push(&row.path);
            params.push(&row.status_code);
            params.push(&row.request_headers);
            params.push(&row.req_body_str);
            params.push(&row.response_headers);
            params.push(&row.resp_body_str);
            params.push(&row.content_type);
            params.push(&row.duration_ms);
            params.push(&row.is_graphql);
            params.push(&row.graphql_operation);
            params.push(&row.graphql_query);
            params.push(&row.graphql_variables);
            params.push(&row.size_bytes);
        }

        let inserted_rows = match tx.query(&sql, &params).await {
            Ok(rows) => rows,
            Err(e) => {
                error!(
                    "[Storage] Vectorized multi-row insert error on public.requests: {}",
                    e
                );
                return;
            }
        };

        if let Err(e) = tx.commit().await {
            error!("[Storage] Failed to commit batch transaction: {}", e);
            return;
        }

        if let Some(eb) = event_bus {
            for (idx, db_row) in inserted_rows.iter().enumerate() {
                if let Some(Some(ref req_uuid)) = row_data.get(idx).map(|r| &r.req_uuid) {
                    let row_id: i32 = db_row.get("id");
                    eb.broadcast_ws(
                        "update_id",
                        json!({
                            "req_uuid": req_uuid,
                            "row_id": row_id,
                        }),
                    );
                }
            }
        }
    }

    pub async fn query_requests(&self, filter: &RequestFilter) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => {
                error!("[Storage] query_requests error: {}", e);
                return Value::Array(Vec::new());
            }
        };

        let mut conditions = Vec::new();
        let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Sync + Send>> = Vec::new();
        let mut idx = 1;

        if let Some(ref domain) = filter.domain {
            if !domain.is_empty() {
                conditions.push(format!("domain ILIKE ${}", idx));
                params.push(Box::new(format!("%{}%", domain)));
                idx += 1;
            }
        }
        if let Some(ref method) = filter.method {
            if !method.is_empty() {
                conditions.push(format!("method = ${}", idx));
                params.push(Box::new(method.to_uppercase()));
                idx += 1;
            }
        }
        if let Some(status) = filter.status_code {
            conditions.push(format!("status_code = ${}", idx));
            params.push(Box::new(status));
            idx += 1;
        }
        if let Some(ref ct) = filter.content_type {
            if !ct.is_empty() {
                conditions.push(format!("response_content_type ILIKE ${}", idx));
                params.push(Box::new(format!("%{}%", ct)));
                idx += 1;
            }
        }
        if let Some(is_gql) = filter.is_graphql {
            conditions.push(format!("is_graphql = ${}", idx));
            params.push(Box::new(if is_gql { 1_i32 } else { 0_i32 }));
            idx += 1;
        }
        if let Some(ref search) = filter.search {
            let trimmed = search.trim();
            if !trimmed.is_empty() {
                let words: Vec<String> = trimmed
                    .split_whitespace()
                    .map(|w| format!("{}:*", w.replace(['\'', '&', '|'], "")))
                    .filter(|w| w != ":*")
                    .collect();
                if !words.is_empty() {
                    let ts_query = words.join(" & ");
                    conditions.push(format!("search_vector @@ to_tsquery('simple', ${})", idx));
                    params.push(Box::new(ts_query));
                }
            }
        }

        let where_clause = if conditions.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", conditions.join(" AND "))
        };

        let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
            .iter()
            .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();

        let limit = filter.limit.unwrap_or(100).clamp(1, 1000);
        let offset = filter.offset.unwrap_or(0).max(0);

        let data_sql = format!(
            "SELECT id, timestamp, timestamp_epoch, method, url, domain, path, status_code,
                    response_content_type, duration_ms, is_graphql, graphql_operation, response_size
             FROM public.requests
             {}
             ORDER BY timestamp_epoch DESC
             LIMIT {} OFFSET {}",
            where_clause, limit, offset
        );

        let rows = client
            .query(&data_sql, &param_refs)
            .await
            .unwrap_or_default();
        let items: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                let id_val: i32 = r.get("id");
                let ts_epoch: f64 = r.get("timestamp_epoch");
                let dt: String = r.get("timestamp");
                let domain_str: String = r.get("domain");
                let path_str: Option<String> = r.get("path");
                let is_gql: i32 = r.get("is_graphql");
                let size_val: Option<i32> = r.get("response_size");
                let ct_val: Option<String> = r.get("response_content_type");
                json!({
                    "id": id_val,
                    "timestamp": dt,
                    "timestamp_epoch": ts_epoch,
                    "datetime": dt,
                    "method": r.get::<_, String>("method"),
                    "url": r.get::<_, String>("url"),
                    "domain": domain_str,
                    "host": domain_str,
                    "path": path_str.unwrap_or_else(|| "/".to_string()),
                    "status_code": r.get::<_, Option<i32>>("status_code"),
                    "content_type": ct_val,
                    "response_content_type": ct_val,
                    "duration_ms": r.get::<_, Option<f64>>("duration_ms"),
                    "is_graphql": is_gql,
                    "graphql_operation": r.get::<_, Option<String>>("graphql_operation"),
                    "response_size": size_val.unwrap_or(0),
                    "size_bytes": size_val.unwrap_or(0),
                })
            })
            .collect();

        Value::Array(items)
    }

    pub async fn get_request(&self, request_id: i64) -> Option<Value> {
        let client = self.pool.get().await.ok()?;
        let req_id_i32 = request_id as i32;
        let row = client
            .query_opt(
                "SELECT id, timestamp, timestamp_epoch, method, url, domain, path, status_code,
                        request_headers, request_body, response_headers, response_body,
                        response_content_type, duration_ms, is_graphql, graphql_operation,
                        graphql_doc_id, graphql_variables, response_size
                 FROM public.requests WHERE id = $1",
                &[&req_id_i32],
            )
            .await
            .ok()??;

        Some(Self::row_to_full_json(&row))
    }

    pub async fn get_requests_for_export(&self, filter: &RequestFilter) -> Vec<Value> {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };

        let mut conditions = Vec::new();
        let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Sync + Send>> = Vec::new();
        let mut idx = 1;

        if let Some(ref domain) = filter.domain {
            if !domain.is_empty() {
                conditions.push(format!("domain ILIKE ${}", idx));
                params.push(Box::new(format!("%{}%", domain)));
                idx += 1;
            }
        }
        if let Some(ref method) = filter.method {
            if !method.is_empty() {
                conditions.push(format!("method = ${}", idx));
                params.push(Box::new(method.to_uppercase()));
                idx += 1;
            }
        }
        if let Some(status) = filter.status_code {
            conditions.push(format!("status_code = ${}", idx));
            params.push(Box::new(status));
            idx += 1;
        }
        if let Some(is_gql) = filter.is_graphql {
            conditions.push(format!("is_graphql = ${}", idx));
            params.push(Box::new(if is_gql { 1_i32 } else { 0_i32 }));
        }

        let where_clause = if conditions.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", conditions.join(" AND "))
        };

        let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
            .iter()
            .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();

        let limit = filter.limit.unwrap_or(500).clamp(1, 5000);
        let sql = format!(
            "SELECT id, timestamp, timestamp_epoch, method, url, domain, path, status_code,
                    request_headers, request_body, response_headers, response_body,
                    response_content_type, duration_ms, is_graphql, graphql_operation,
                    graphql_doc_id, graphql_variables, response_size
             FROM public.requests
             {}
             ORDER BY timestamp_epoch DESC
             LIMIT {}",
            where_clause, limit
        );

        let rows = client.query(&sql, &param_refs).await.unwrap_or_default();
        rows.iter().map(Self::row_to_full_json).collect()
    }

    fn row_to_full_json(row: &tokio_postgres::Row) -> Value {
        let id_val: i32 = row.get("id");
        let ts_epoch: f64 = row.get("timestamp_epoch");
        let dt: String = row.get("timestamp");
        let domain_str: String = row.get("domain");
        let path_str: Option<String> = row.get("path");

        let req_headers_str: Option<String> = row.get("request_headers");
        let resp_headers_str: Option<String> = row.get("response_headers");

        let req_headers: Value = req_headers_str
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));
        let resp_headers: Value = resp_headers_str
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));

        let req_body_str: Option<String> = row.get("request_body");
        let resp_body_str: Option<String> = row.get("response_body");

        let is_gql: i32 = row.get("is_graphql");
        let gql_vars_str: Option<String> = row.get("graphql_variables");
        let size_val: Option<i32> = row.get("response_size");
        let ct_val: Option<String> = row.get("response_content_type");

        json!({
            "id": id_val,
            "timestamp": dt,
            "timestamp_epoch": ts_epoch,
            "datetime": dt,
            "method": row.get::<_, String>("method"),
            "url": row.get::<_, String>("url"),
            "domain": domain_str,
            "host": domain_str,
            "path": path_str.unwrap_or_else(|| "/".to_string()),
            "status_code": row.get::<_, Option<i32>>("status_code"),
            "content_type": ct_val,
            "response_content_type": ct_val,
            "duration_ms": row.get::<_, Option<f64>>("duration_ms"),
            "is_graphql": is_gql,
            "graphql_operation": row.get::<_, Option<String>>("graphql_operation"),
            "graphql_doc_id": row.get::<_, Option<String>>("graphql_doc_id"),
            "graphql_variables": gql_vars_str,
            "response_size": size_val.unwrap_or(0),
            "size_bytes": size_val.unwrap_or(0),
            "request_headers": req_headers,
            "request_body": req_body_str,
            "response_headers": resp_headers,
            "response_body": resp_body_str,
        })
    }

    pub async fn get_domains(&self) -> Vec<Value> {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };
        let rows = client
            .query(
                "SELECT domain, COUNT(*) as count,
                        SUM(CASE WHEN is_graphql = 1 THEN 1 ELSE 0 END) as graphql_count
                 FROM public.requests
                 GROUP BY domain
                 ORDER BY count DESC",
                &[],
            )
            .await
            .unwrap_or_default();

        rows.into_iter()
            .map(|r| {
                let d: String = r.get("domain");
                json!({
                    "domain": d,
                    "host": d,
                    "count": r.get::<_, i64>("count"),
                    "graphql_count": r.get::<_, Option<i64>>("graphql_count").unwrap_or(0),
                })
            })
            .collect()
    }

    pub async fn get_stats(&self) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => {
                return json!({
                    "requests": 0,
                    "domains": 0,
                    "graphql": 0,
                    "total_requests": 0,
                    "graphql_requests": 0,
                    "unique_domains": 0,
                    "total_size_bytes": 0,
                    "methods": {}
                })
            }
        };

        let (total, graphql_count, domain_count, total_size): (i64, i64, i64, i64) = client
            .query_one(
                "SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN is_graphql = 1 THEN 1 ELSE 0 END), 0),
                    COUNT(DISTINCT domain),
                    COALESCE(SUM(response_size), 0)::bigint
                 FROM public.requests",
                &[],
            )
            .await
            .map(|r| (r.get(0), r.get(1), r.get(2), r.get(3)))
            .unwrap_or((0, 0, 0, 0));

        let method_rows = client
            .query(
                "SELECT method, COUNT(*) as count FROM public.requests GROUP BY method",
                &[],
            )
            .await
            .unwrap_or_default();
        let mut methods = HashMap::new();
        for r in method_rows {
            let m: String = r.get("method");
            let c: i64 = r.get("count");
            methods.insert(m, c);
        }

        json!({
            "requests": total,
            "domains": domain_count,
            "graphql": graphql_count,
            "total_requests": total,
            "graphql_requests": graphql_count,
            "unique_domains": domain_count,
            "total_size_bytes": total_size,
            "methods": methods,
        })
    }

    pub async fn delete_requests(&self, domain: Option<&str>) -> u64 {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return 0,
        };
        if let Some(d) = domain {
            if !d.is_empty() {
                return client
                    .execute(
                        "DELETE FROM public.requests WHERE domain ILIKE $1",
                        &[&format!("%{}%", d)],
                    )
                    .await
                    .unwrap_or(0);
            }
        }
        client
            .batch_execute("TRUNCATE TABLE public.requests RESTART IDENTITY")
            .await
            .map(|_| 1)
            .unwrap_or(0)
    }
}
