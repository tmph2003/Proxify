use chrono::{DateTime, FixedOffset, Utc};
use deadpool_postgres::Pool;
use serde_json::{json, Value};
use std::sync::Arc;
use tracing::{error, info};

pub struct FacebookStorage {
    pool: Pool,
}

impl FacebookStorage {
    pub fn new(pool: Pool) -> Arc<Self> {
        Arc::new(Self { pool })
    }

    pub async fn init_schema(&self) -> Result<(), String> {
        let client = self
            .pool
            .get()
            .await
            .map_err(|e| format!("Facebook DB connect error: {}", e))?;

        client
            .batch_execute(
                r#"
                CREATE SCHEMA IF NOT EXISTS facebook;

                CREATE TABLE IF NOT EXISTS facebook.authors (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    profile_url TEXT,
                    avatar_url TEXT,
                    typename TEXT,
                    first_seen TEXT,
                    last_seen TEXT
                );

                CREATE TABLE IF NOT EXISTS facebook.posts (
                    post_id TEXT PRIMARY KEY,
                    group_id TEXT,
                    group_name TEXT,
                    author_id TEXT REFERENCES facebook.authors(id),
                    author_name TEXT,
                    message_text TEXT,
                    permalink_url TEXT,
                    creation_time DOUBLE PRECISION,
                    creation_datetime TEXT,
                    attachments TEXT,
                    seo_title TEXT,
                    is_text_only INTEGER DEFAULT 0,
                    reaction_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    share_count INTEGER DEFAULT 0,
                    extracted_at TEXT,
                    raw_source_request_id INTEGER,
                    search_vector tsvector,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    feedback_id TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    group_numeric_id TEXT
                );

                CREATE TABLE IF NOT EXISTS facebook.comments (
                    comment_id TEXT PRIMARY KEY,
                    post_id TEXT REFERENCES facebook.posts(post_id),
                    parent_comment_id TEXT,
                    author_id TEXT REFERENCES facebook.authors(id),
                    author_name TEXT,
                    body_text TEXT,
                    creation_time DOUBLE PRECISION,
                    creation_datetime TEXT,
                    reaction_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    extracted_at TEXT,
                    search_vector tsvector
                );

                CREATE TABLE IF NOT EXISTS facebook.attachments (
                    id SERIAL PRIMARY KEY,
                    post_id TEXT REFERENCES facebook.posts(post_id),
                    comment_id TEXT,
                    type TEXT,
                    url TEXT,
                    title TEXT,
                    description TEXT
                );

                CREATE TABLE IF NOT EXISTS facebook.config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_posts_group ON facebook.posts(group_id);
                CREATE INDEX IF NOT EXISTS idx_posts_author ON facebook.posts(author_id);
                CREATE INDEX IF NOT EXISTS idx_posts_created ON facebook.posts(creation_time);
                CREATE INDEX IF NOT EXISTS idx_comments_post ON facebook.comments(post_id);
                "#,
            )
            .await
            .map_err(|e| format!("Facebook schema init failed: {}", e))?;

        info!("[FacebookStorage] Schema 'facebook' initialized.");
        Ok(())
    }

    pub async fn save_config(&self, key: &str, value: &Value) {
        if let Ok(client) = self.pool.get().await {
            let val_str = match value {
                Value::String(s) => s.clone(),
                _ => serde_json::to_string(value).unwrap_or_else(|_| "{}".to_string()),
            };
            let _ = client
                .execute(
                    r#"
                    INSERT INTO facebook.config (key, value, updated_at)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = CURRENT_TIMESTAMP
                    "#,
                    &[&key, &val_str],
                )
                .await;
        }
    }

    pub async fn save_config_str(&self, key: &str, val_str: &str) {
        if let Ok(client) = self.pool.get().await {
            let _ = client
                .execute(
                    r#"
                    INSERT INTO facebook.config (key, value, updated_at)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = CURRENT_TIMESTAMP
                    "#,
                    &[&key, &val_str],
                )
                .await;
        }
    }

    pub async fn load_config(&self, key: &str) -> Option<Value> {
        let client = self.pool.get().await.ok()?;
        let row = client
            .query_opt("SELECT value FROM facebook.config WHERE key = $1", &[&key])
            .await
            .ok()??;
        let val_str: String = row.get("value");
        serde_json::from_str(&val_str)
            .ok()
            .or(Some(Value::String(val_str)))
    }

    pub async fn load_config_str(&self, key: &str) -> Option<String> {
        let client = self.pool.get().await.ok()?;
        let row = client
            .query_opt("SELECT value FROM facebook.config WHERE key = $1", &[&key])
            .await
            .ok()??;
        row.get("value")
    }

    pub async fn get_token_status(&self) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return json!({ "has_dtsg": false, "templates": [] }),
        };
        let rows = client
            .query(
                "SELECT key, updated_at::text as updated_at FROM facebook.config",
                &[],
            )
            .await
            .unwrap_or_default();

        let mut has_dtsg = false;
        let mut dtsg_updated: Option<String> = None;
        let mut templates = Vec::new();

        for r in rows {
            let k: String = r.get("key");
            let updated: Option<String> = r.get("updated_at");
            if k == "last_fb_dtsg" || k == "fb_dtsg" {
                has_dtsg = true;
                dtsg_updated = updated;
            } else if let Some(friendly) = k.strip_prefix("template_") {
                templates.push(friendly.to_string());
            }
        }

        json!({
            "has_dtsg": has_dtsg,
            "dtsg_updated": dtsg_updated,
            "templates": templates,
        })
    }

    fn format_vn_datetime(epoch_secs: i64) -> Option<String> {
        if epoch_secs <= 0 {
            return None;
        }
        let tz = FixedOffset::east_opt(7 * 3600)?;
        let dt = DateTime::<Utc>::from_timestamp(epoch_secs, 0)?.with_timezone(&tz);
        Some(dt.format("%Y-%m-%d %H:%M:%S").to_string())
    }

    pub async fn save_post(&self, post: &Value) -> bool {
        let post_id = match post.get("post_id").and_then(|v| v.as_str()) {
            Some(id) if !id.is_empty() => id,
            _ => return false,
        };

        let mut client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => {
                error!("[FacebookStorage] DB connect error: {}", e);
                return false;
            }
        };

        let tx = match client.transaction().await {
            Ok(t) => t,
            Err(_) => return false,
        };

        let now_iso = Utc::now().to_rfc3339();
        let author = post.get("author").cloned().unwrap_or_else(|| json!({}));
        let author_id = author
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let author_name = author
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown");
        let author_url = author.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let author_avatar = author.get("avatar").and_then(|v| v.as_str()).unwrap_or("");

        let _ = tx
            .execute(
                r#"
                INSERT INTO facebook.authors (id, name, profile_url, avatar_url, first_seen, last_seen)
                VALUES ($1, $2, $3, $4, $5, $5)
                ON CONFLICT (id) DO UPDATE SET
                    name = CASE WHEN EXCLUDED.name <> 'Unknown' THEN EXCLUDED.name ELSE facebook.authors.name END,
                    profile_url = CASE WHEN EXCLUDED.profile_url <> '' THEN EXCLUDED.profile_url ELSE facebook.authors.profile_url END,
                    avatar_url = CASE WHEN EXCLUDED.avatar_url <> '' THEN EXCLUDED.avatar_url ELSE facebook.authors.avatar_url END,
                    last_seen = EXCLUDED.last_seen
                "#,
                &[&author_id, &author_name, &author_url, &author_avatar, &now_iso],
            )
            .await;

        let group_id = post
            .get("group_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let group_name = post.get("group_name").and_then(|v| v.as_str());
        let feedback_id = post.get("feedback_id").and_then(|v| v.as_str());
        let url = post.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let created_at_secs = post.get("created_at").and_then(|v| v.as_i64()).unwrap_or(0);
        let created_at = created_at_secs as f64;
        let creation_dt = Self::format_vn_datetime(created_at_secs);
        let content = post.get("content").and_then(|v| v.as_str()).unwrap_or("");
        let stats = post.get("stats").cloned().unwrap_or_else(|| json!({}));
        let reactions = stats.get("reactions").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        let comments_cnt = stats.get("comments").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        let shares = stats.get("shares").and_then(|v| v.as_i64()).unwrap_or(0) as i32;

        let _ = tx
            .execute(
                r#"
                INSERT INTO facebook.posts (
                    post_id, group_id, group_name, author_id, author_name, permalink_url,
                    creation_time, creation_datetime, message_text, feedback_id,
                    reaction_count, comment_count, share_count, is_active, extracted_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, TRUE, $14, CURRENT_TIMESTAMP)
                ON CONFLICT (post_id) DO UPDATE SET
                    group_id = CASE WHEN EXCLUDED.group_id <> 'unknown' THEN EXCLUDED.group_id ELSE facebook.posts.group_id END,
                    group_name = COALESCE(EXCLUDED.group_name, facebook.posts.group_name),
                    feedback_id = COALESCE(EXCLUDED.feedback_id, facebook.posts.feedback_id),
                    creation_datetime = COALESCE(EXCLUDED.creation_datetime, facebook.posts.creation_datetime),
                    message_text = CASE WHEN LENGTH(EXCLUDED.message_text) > LENGTH(COALESCE(facebook.posts.message_text, '')) THEN EXCLUDED.message_text ELSE facebook.posts.message_text END,
                    reaction_count = GREATEST(EXCLUDED.reaction_count, facebook.posts.reaction_count),
                    comment_count = GREATEST(EXCLUDED.comment_count, facebook.posts.comment_count),
                    share_count = GREATEST(EXCLUDED.share_count, facebook.posts.share_count),
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                "#,
                &[
                    &post_id,
                    &group_id,
                    &group_name,
                    &author_id,
                    &author_name,
                    &url,
                    &created_at,
                    &creation_dt,
                    &content,
                    &feedback_id,
                    &reactions,
                    &comments_cnt,
                    &shares,
                    &now_iso,
                ],
            )
            .await;

        if let Some(atts) = post.get("attachments").and_then(|v| v.as_array()) {
            let _ = tx
                .execute(
                    "DELETE FROM facebook.attachments WHERE post_id = $1",
                    &[&post_id],
                )
                .await;
            for att in atts {
                let atype = att.get("type").and_then(|v| v.as_str()).unwrap_or("Link");
                let aurl = att.get("url").and_then(|v| v.as_str()).unwrap_or("");
                let atitle = att.get("title").and_then(|v| v.as_str()).unwrap_or("");
                if !aurl.is_empty() {
                    let _ = tx
                        .execute(
                            r#"
                            INSERT INTO facebook.attachments (post_id, type, url, title)
                            VALUES ($1, $2, $3, $4)
                            "#,
                            &[&post_id, &atype, &aurl, &atitle],
                        )
                        .await;
                }
            }
        }

        if let Some(comments) = post.get("comments").and_then(|v| v.as_array()) {
            for c in comments {
                Self::insert_comment_in_tx(&tx, c, post_id, &now_iso).await;
            }
        }

        tx.commit().await.is_ok()
    }

    pub async fn save_standalone_comments(&self, comments: &[Value], post_id: &str) -> usize {
        if comments.is_empty() {
            return 0;
        }
        let mut client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return 0,
        };
        let tx = match client.transaction().await {
            Ok(t) => t,
            Err(_) => return 0,
        };

        let _ = tx
            .execute(
                r#"
                INSERT INTO facebook.posts (post_id, group_id, message_text, is_active)
                VALUES ($1, 'unknown', '', TRUE)
                ON CONFLICT (post_id) DO NOTHING
                "#,
                &[&post_id],
            )
            .await;

        let now_iso = Utc::now().to_rfc3339();
        let mut count = 0;
        for c in comments {
            if Self::insert_comment_in_tx(&tx, c, post_id, &now_iso).await {
                count += 1;
            }
        }
        let _ = tx.commit().await;
        count
    }

    async fn insert_comment_in_tx(
        tx: &deadpool_postgres::Transaction<'_>,
        c: &Value,
        default_post_id: &str,
        now_iso: &str,
    ) -> bool {
        let cid = match c.get("comment_id").and_then(|v| v.as_str()) {
            Some(id) if !id.is_empty() => id,
            _ => return false,
        };
        let pid = c
            .get("post_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(default_post_id);

        let author = c.get("author").cloned().unwrap_or_else(|| json!({}));
        let author_id = author
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let author_name = author
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown");
        let author_url = author.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let author_avatar = author.get("avatar").and_then(|v| v.as_str()).unwrap_or("");

        let _ = tx
            .execute(
                r#"
                INSERT INTO facebook.authors (id, name, profile_url, avatar_url, first_seen, last_seen)
                VALUES ($1, $2, $3, $4, $5, $5)
                ON CONFLICT (id) DO UPDATE SET
                    name = CASE WHEN EXCLUDED.name <> 'Unknown' THEN EXCLUDED.name ELSE facebook.authors.name END,
                    avatar_url = CASE WHEN EXCLUDED.avatar_url <> '' THEN EXCLUDED.avatar_url ELSE facebook.authors.avatar_url END,
                    last_seen = EXCLUDED.last_seen
                "#,
                &[&author_id, &author_name, &author_url, &author_avatar, &now_iso],
            )
            .await;

        let parent_id = c.get("parent_id").and_then(|v| v.as_str());
        let created_secs = c.get("created_at").and_then(|v| v.as_i64()).unwrap_or(0);
        let created_at = created_secs as f64;
        let creation_dt = Self::format_vn_datetime(created_secs);
        let content = c.get("content").and_then(|v| v.as_str()).unwrap_or("");
        let reactions = c
            .get("reaction_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0) as i32;

        let res = tx
            .execute(
                r#"
                INSERT INTO facebook.comments (
                    comment_id, post_id, parent_comment_id, author_id, author_name,
                    creation_time, creation_datetime, body_text, reaction_count, extracted_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (comment_id) DO UPDATE SET
                    creation_datetime = COALESCE(EXCLUDED.creation_datetime, facebook.comments.creation_datetime),
                    body_text = CASE WHEN LENGTH(EXCLUDED.body_text) > LENGTH(COALESCE(facebook.comments.body_text, '')) THEN EXCLUDED.body_text ELSE facebook.comments.body_text END
                "#,
                &[
                    &cid,
                    &pid,
                    &parent_id,
                    &author_id,
                    &author_name,
                    &created_at,
                    &creation_dt,
                    &content,
                    &reactions,
                    &now_iso,
                ],
            )
            .await;

        res.is_ok()
    }

    pub async fn get_groups_list(&self) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => return json!({ "status": "error", "message": e.to_string(), "data": [] }),
        };

        let rows = client
            .query(
                r#"
                SELECT 
                    MAX(
                        COALESCE(
                            NULLIF(trim(group_id), ''), 
                            substring(permalink_url from '/groups/([^/]+)/')
                        )
                    ) as group_id, 
                    trim(group_name) as group_name
                FROM facebook.posts
                WHERE group_name IS NOT NULL AND trim(group_name) != ''
                GROUP BY trim(group_name)
                ORDER BY lower(trim(group_name)) ASC
                "#,
                &[],
            )
            .await
            .unwrap_or_default();

        let data: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                json!({
                    "group_id": r.get::<_, Option<String>>("group_id"),
                    "group_name": r.get::<_, Option<String>>("group_name"),
                })
            })
            .collect();

        json!({ "status": "ok", "data": data })
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn query_results(
        &self,
        sort: &str,
        order: &str,
        group_id: &str,
        group_name: &str,
        status_filter: &str,
        start_date: &str,
        end_date: &str,
        page: i64,
        limit: i64,
    ) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => {
                return json!({ "status": "error", "message": e.to_string(), "data": [], "total": 0 })
            }
        };

        let ord = if order.eq_ignore_ascii_case("ASC") {
            "ASC"
        } else {
            "DESC"
        };
        let order_clause = match sort {
            "reaction" => format!("ORDER BY p.reaction_count {} NULLS LAST", ord),
            "comment" => format!("ORDER BY p.comment_count {} NULLS LAST", ord),
            "author" => format!("ORDER BY p.author_name {} NULLS LAST", ord),
            "content" => format!("ORDER BY p.message_text {} NULLS LAST", ord),
            "updated" => format!("ORDER BY p.updated_at {} NULLS LAST", ord),
            _ => format!("ORDER BY p.creation_time {} NULLS LAST", ord),
        };

        let mut conditions: Vec<String> = Vec::new();
        let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Sync + Send>> = Vec::new();
        let mut idx = 1;

        if !group_id.is_empty() && !group_name.is_empty() {
            conditions.push(format!(
                "(p.group_id = ${} OR p.group_name = ${})",
                idx,
                idx + 1
            ));
            params.push(Box::new(group_id.to_string()));
            params.push(Box::new(group_name.to_string()));
            idx += 2;
        } else if !group_id.is_empty() {
            conditions.push(format!("p.group_id = ${}", idx));
            params.push(Box::new(group_id.to_string()));
            idx += 1;
        } else if !group_name.is_empty() {
            conditions.push(format!("p.group_name = ${}", idx));
            params.push(Box::new(group_name.to_string()));
            idx += 1;
        }

        match status_filter {
            "active" => conditions.push("p.is_active = TRUE".to_string()),
            "inactive" => conditions.push("p.is_active = FALSE".to_string()),
            "unknown" => conditions.push("p.is_active IS NULL".to_string()),
            _ => {}
        }

        if !start_date.is_empty() {
            if let Ok(nd) = chrono::NaiveDate::parse_from_str(start_date, "%Y-%m-%d") {
                if let Some(dt) = nd.and_hms_opt(0, 0, 0) {
                    let ts = dt.and_utc().timestamp() as f64;
                    conditions.push(format!("p.creation_time >= ${}", idx));
                    params.push(Box::new(ts));
                    idx += 1;
                }
            }
        }
        if !end_date.is_empty() {
            if let Ok(nd) = chrono::NaiveDate::parse_from_str(end_date, "%Y-%m-%d") {
                if let Some(dt) = nd.and_hms_opt(0, 0, 0) {
                    let ts = (dt.and_utc().timestamp() + 86400) as f64;
                    conditions.push(format!("p.creation_time <= ${}", idx));
                    params.push(Box::new(ts));
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

        let count_sql = format!("SELECT COUNT(*) FROM facebook.posts p {}", where_clause);
        let total: i64 = client
            .query_one(&count_sql, &param_refs)
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);

        let safe_page = page.max(1);
        let safe_limit = limit.clamp(1, 500);
        let offset = (safe_page - 1) * safe_limit;

        let query_posts = format!(
            r#"
            SELECT p.post_id, p.author_name, a.profile_url, a.avatar_url,
                   p.creation_datetime, p.creation_time, p.message_text,
                   p.permalink_url, p.reaction_count, p.comment_count,
                   p.feedback_id, p.is_active,
                   (p.created_at + INTERVAL '7 hours')::text as created_at,
                   (p.updated_at + INTERVAL '7 hours')::text as updated_at,
                   (SELECT COUNT(*) FROM facebook.comments c2 WHERE c2.post_id = p.post_id) as crawled_comment_count
            FROM facebook.posts p
            LEFT JOIN facebook.authors a ON p.author_id = a.id
            {}
            {}
            LIMIT {} OFFSET {}
            "#,
            where_clause, order_clause, safe_limit, offset
        );

        let rows = client
            .query(&query_posts, &param_refs)
            .await
            .unwrap_or_default();
        let data: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                let c_dt: Option<String> = r.get("creation_datetime");
                let c_time: Option<f64> = r.get("creation_time");
                let resolved_dt = c_dt.or_else(|| c_time.and_then(|t| Self::format_vn_datetime(t as i64)));
                json!({
                    "post_id": r.get::<_, String>("post_id"),
                    "author_name": r.get::<_, Option<String>>("author_name"),
                    "profile_url": r.get::<_, Option<String>>("profile_url"),
                    "avatar_url": r.get::<_, Option<String>>("avatar_url"),
                    "creation_datetime": resolved_dt,
                    "message_text": r.get::<_, Option<String>>("message_text"),
                    "permalink_url": r.get::<_, Option<String>>("permalink_url"),
                    "reaction_count": r.get::<_, Option<i32>>("reaction_count").unwrap_or(0),
                    "comment_count": r.get::<_, Option<i32>>("comment_count").unwrap_or(0),
                    "feedback_id": r.get::<_, Option<String>>("feedback_id"),
                    "is_active": r.get::<_, Option<bool>>("is_active"),
                    "created_at": r.get::<_, Option<String>>("created_at"),
                    "updated_at": r.get::<_, Option<String>>("updated_at"),
                    "crawled_comment_count": r.get::<_, Option<i64>>("crawled_comment_count").unwrap_or(0),
                })
            })
            .collect();

        json!({
            "status": "ok",
            "data": data,
            "total": total,
            "page": safe_page,
            "limit": safe_limit,
        })
    }

    pub async fn get_comments_for_post(&self, post_id: &str) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => {
                return json!({ "status": "error", "message": e.to_string(), "data": [], "total": 0 })
            }
        };

        let rows = client
            .query(
                r#"
                SELECT c.comment_id, c.post_id, c.parent_comment_id,
                       c.author_id, c.author_name, c.body_text,
                       c.body_text AS message_text,
                       c.creation_time, c.creation_datetime,
                       c.reaction_count, c.reply_count,
                       a.avatar_url,
                       a.avatar_url AS author_avatar
                FROM facebook.comments c
                LEFT JOIN facebook.authors a ON c.author_id = a.id
                WHERE c.post_id = $1
                ORDER BY c.creation_time ASC NULLS LAST
                "#,
                &[&post_id],
            )
            .await
            .unwrap_or_default();

        let data: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                let c_dt: Option<String> = r.get("creation_datetime");
                let c_time: Option<f64> = r.get("creation_time");
                let resolved_dt =
                    c_dt.or_else(|| c_time.and_then(|t| Self::format_vn_datetime(t as i64)));
                json!({
                    "comment_id": r.get::<_, String>("comment_id"),
                    "post_id": r.get::<_, Option<String>>("post_id"),
                    "parent_comment_id": r.get::<_, Option<String>>("parent_comment_id"),
                    "author_id": r.get::<_, Option<String>>("author_id"),
                    "author_name": r.get::<_, Option<String>>("author_name"),
                    "body_text": r.get::<_, Option<String>>("body_text"),
                    "message_text": r.get::<_, Option<String>>("message_text"),
                    "creation_time": c_time,
                    "creation_datetime": resolved_dt,
                    "reaction_count": r.get::<_, Option<i32>>("reaction_count").unwrap_or(0),
                    "reply_count": r.get::<_, Option<i32>>("reply_count").unwrap_or(0),
                    "avatar_url": r.get::<_, Option<String>>("avatar_url"),
                    "author_avatar": r.get::<_, Option<String>>("author_avatar"),
                })
            })
            .collect();

        let total = data.len();
        json!({
            "status": "ok",
            "data": data,
            "total": total,
        })
    }

    pub async fn update_post_status(&self, post_ids: &[String], is_active: Option<bool>) -> usize {
        if post_ids.is_empty() {
            return 0;
        }
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return 0,
        };
        let res = match is_active {
            Some(active) => {
                client
                    .execute(
                        "UPDATE facebook.posts SET is_active = $1, updated_at = CURRENT_TIMESTAMP WHERE post_id = ANY($2::text[])",
                        &[&active, &post_ids],
                    )
                    .await
            }
            None => {
                client
                    .execute(
                        "UPDATE facebook.posts SET is_active = NULL, updated_at = CURRENT_TIMESTAMP WHERE post_id = ANY($1::text[])",
                        &[&post_ids],
                    )
                    .await
            }
        };
        res.unwrap_or(0) as usize
    }

    pub async fn delete_posts(&self, post_ids: &[String]) -> usize {
        if post_ids.is_empty() {
            return 0;
        }
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return 0,
        };
        let _ = client
            .execute(
                "DELETE FROM facebook.attachments WHERE post_id = ANY($1::text[])",
                &[&post_ids],
            )
            .await;
        let _ = client
            .execute(
                "DELETE FROM facebook.comments WHERE post_id = ANY($1::text[])",
                &[&post_ids],
            )
            .await;
        client
            .execute(
                "DELETE FROM facebook.posts WHERE post_id = ANY($1::text[])",
                &[&post_ids],
            )
            .await
            .unwrap_or(0) as usize
    }

    pub async fn export_posts_csv(&self, post_ids: &[String]) -> String {
        let mut out = String::from(
            "post_id,author_name,creation_datetime,message_text,permalink_url,reaction_count,comment_count,crawled_comments,is_active\n",
        );
        if post_ids.is_empty() {
            return out;
        }
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return out,
        };
        let rows = client
            .query(
                r#"
                SELECT p.post_id, p.author_name, p.creation_datetime,
                       p.message_text, p.permalink_url, p.reaction_count,
                       p.comment_count, p.is_active,
                       (SELECT COUNT(*) FROM facebook.comments c WHERE c.post_id = p.post_id) as crawled_comments
                FROM facebook.posts p
                WHERE p.post_id = ANY($1::text[])
                ORDER BY p.creation_time DESC NULLS LAST
                "#,
                &[&post_ids],
            )
            .await
            .unwrap_or_default();

        for r in rows {
            let pid: String = r.get("post_id");
            let author = r
                .get::<_, Option<String>>("author_name")
                .unwrap_or_default();
            let c_dt = r
                .get::<_, Option<String>>("creation_datetime")
                .unwrap_or_default();
            let msg = r
                .get::<_, Option<String>>("message_text")
                .unwrap_or_default()
                .replace('"', "\"\"");
            let url = r
                .get::<_, Option<String>>("permalink_url")
                .unwrap_or_default();
            let rc = r.get::<_, Option<i32>>("reaction_count").unwrap_or(0);
            let cc = r.get::<_, Option<i32>>("comment_count").unwrap_or(0);
            let crawled = r.get::<_, Option<i64>>("crawled_comments").unwrap_or(0);
            let active = match r.get::<_, Option<bool>>("is_active") {
                Some(true) => "Active",
                Some(false) => "Inactive",
                None => "Unknown",
            };
            out.push_str(&format!(
                "\"{}\",\"{}\",\"{}\",\"{}\",\"{}\",{},{},{},{}\n",
                pid,
                author.replace('"', "\"\""),
                c_dt,
                msg,
                url,
                rc,
                cc,
                crawled,
                active
            ));
        }
        out
    }

    pub async fn get_posts(
        &self,
        group_id: Option<&str>,
        search: Option<&str>,
        has_links: bool,
        limit: i64,
        offset: i64,
    ) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return json!({ "total": 0, "posts": [] }),
        };

        let mut conditions = vec!["COALESCE(p.is_active, TRUE) = TRUE".to_string()];
        let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Sync + Send>> = Vec::new();
        let mut idx = 1;

        if let Some(gid) = group_id.filter(|g| !g.trim().is_empty()) {
            conditions.push(format!("p.group_id = ${}", idx));
            params.push(Box::new(gid.trim().to_string()));
            idx += 1;
        }
        if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            conditions.push(format!(
                "(p.message_text ILIKE ${0} OR COALESCE(a.name, p.author_name) ILIKE ${0})",
                idx
            ));
            params.push(Box::new(format!("%{}%", s.trim())));
        }
        if has_links {
            conditions.push(
                "EXISTS (SELECT 1 FROM facebook.attachments att WHERE att.post_id = p.post_id)"
                    .to_string(),
            );
        }

        let where_clause = format!("WHERE {}", conditions.join(" AND "));
        let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
            .iter()
            .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();

        let count_sql = format!(
            "SELECT COUNT(*) FROM facebook.posts p LEFT JOIN facebook.authors a ON p.author_id = a.id {}",
            where_clause
        );
        let total: i64 = client
            .query_one(&count_sql, &param_refs)
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);

        let sql = format!(
            r#"
            SELECT p.post_id, p.group_id, p.permalink_url, p.creation_time, p.message_text,
                   p.reaction_count, p.comment_count, p.share_count,
                   COALESCE(a.id, p.author_id) as author_id,
                   COALESCE(a.name, p.author_name) as author_name,
                   a.profile_url as author_url,
                   a.avatar_url as author_avatar
            FROM facebook.posts p
            LEFT JOIN facebook.authors a ON p.author_id = a.id
            {}
            ORDER BY p.creation_time DESC NULLS LAST, p.updated_at DESC
            LIMIT {} OFFSET {}
            "#,
            where_clause, limit, offset
        );

        let rows = client.query(&sql, &param_refs).await.unwrap_or_default();
        let mut posts = Vec::new();

        for r in rows {
            let pid: String = r.get("post_id");
            let att_rows = client
                .query(
                    "SELECT id, type, url, title FROM facebook.attachments WHERE post_id = $1",
                    &[&pid],
                )
                .await
                .unwrap_or_default();
            let attachments: Vec<Value> = att_rows
                .into_iter()
                .map(|ar| {
                    let aid: i32 = ar.get("id");
                    json!({
                        "id": aid.to_string(),
                        "type": ar.get::<_, Option<String>>("type"),
                        "url": ar.get::<_, Option<String>>("url"),
                        "title": ar.get::<_, Option<String>>("title"),
                    })
                })
                .collect();

            let c_time: Option<f64> = r.get("creation_time");
            let msg: Option<String> = r.get("message_text");
            let p_url: Option<String> = r.get("permalink_url");

            posts.push(json!({
                "id": pid,
                "post_id": pid,
                "group_id": r.get::<_, Option<String>>("group_id"),
                "url": p_url.clone(),
                "permalink_url": p_url,
                "created_at": c_time.map(|t| t as i64),
                "creation_time": c_time,
                "content": msg.clone(),
                "message_text": msg,
                "reaction_count": r.get::<_, Option<i32>>("reaction_count").unwrap_or(0),
                "comment_count": r.get::<_, Option<i32>>("comment_count").unwrap_or(0),
                "share_count": r.get::<_, Option<i32>>("share_count").unwrap_or(0),
                "author": {
                    "id": r.get::<_, Option<String>>("author_id"),
                    "name": r.get::<_, Option<String>>("author_name"),
                    "url": r.get::<_, Option<String>>("author_url"),
                    "avatar": r.get::<_, Option<String>>("author_avatar"),
                },
                "attachments": attachments,
            }));
        }

        json!({ "total": total, "posts": posts })
    }

    pub async fn get_post_detail(&self, post_id: &str) -> Option<Value> {
        let client = self.pool.get().await.ok()?;
        let r = client
            .query_opt(
                r#"
                SELECT p.post_id, p.group_id, p.permalink_url, p.creation_time, p.message_text,
                       p.reaction_count, p.comment_count, p.share_count,
                       COALESCE(a.id, p.author_id) as author_id,
                       COALESCE(a.name, p.author_name) as author_name,
                       a.profile_url as author_url,
                       a.avatar_url as author_avatar
                FROM facebook.posts p
                LEFT JOIN facebook.authors a ON p.author_id = a.id
                WHERE p.post_id = $1 AND COALESCE(p.is_active, TRUE) = TRUE
                "#,
                &[&post_id],
            )
            .await
            .ok()??;

        let att_rows = client
            .query(
                "SELECT id, type, url, title FROM facebook.attachments WHERE post_id = $1",
                &[&post_id],
            )
            .await
            .unwrap_or_default();
        let attachments: Vec<Value> = att_rows
            .into_iter()
            .map(|ar| {
                let aid: i32 = ar.get("id");
                json!({
                    "id": aid.to_string(),
                    "type": ar.get::<_, Option<String>>("type"),
                    "url": ar.get::<_, Option<String>>("url"),
                    "title": ar.get::<_, Option<String>>("title"),
                })
            })
            .collect();

        let c_rows = client
            .query(
                r#"
                SELECT c.comment_id, c.parent_comment_id, c.creation_time, c.body_text, c.reaction_count,
                       COALESCE(a.id, c.author_id) as author_id,
                       COALESCE(a.name, c.author_name) as author_name,
                       a.profile_url as author_url,
                       a.avatar_url as author_avatar
                FROM facebook.comments c
                LEFT JOIN facebook.authors a ON c.author_id = a.id
                WHERE c.post_id = $1
                ORDER BY c.creation_time ASC NULLS LAST
                "#,
                &[&post_id],
            )
            .await
            .unwrap_or_default();

        let comments: Vec<Value> = c_rows
            .into_iter()
            .map(|cr| {
                let cid: String = cr.get("comment_id");
                let c_time: Option<f64> = cr.get("creation_time");
                let body: Option<String> = cr.get("body_text");
                json!({
                    "id": cid,
                    "comment_id": cid,
                    "parent_id": cr.get::<_, Option<String>>("parent_comment_id"),
                    "created_at": c_time.map(|t| t as i64),
                    "creation_time": c_time,
                    "content": body.clone(),
                    "body_text": body,
                    "reaction_count": cr.get::<_, Option<i32>>("reaction_count").unwrap_or(0),
                    "author": {
                        "id": cr.get::<_, Option<String>>("author_id"),
                        "name": cr.get::<_, Option<String>>("author_name"),
                        "url": cr.get::<_, Option<String>>("author_url"),
                        "avatar": cr.get::<_, Option<String>>("author_avatar"),
                    }
                })
            })
            .collect();

        let pid: String = r.get("post_id");
        let c_time: Option<f64> = r.get("creation_time");
        let msg: Option<String> = r.get("message_text");
        let p_url: Option<String> = r.get("permalink_url");

        Some(json!({
            "id": pid,
            "post_id": pid,
            "group_id": r.get::<_, Option<String>>("group_id"),
            "url": p_url.clone(),
            "permalink_url": p_url,
            "created_at": c_time.map(|t| t as i64),
            "creation_time": c_time,
            "content": msg.clone(),
            "message_text": msg,
            "reaction_count": r.get::<_, Option<i32>>("reaction_count").unwrap_or(0),
            "comment_count": r.get::<_, Option<i32>>("comment_count").unwrap_or(0),
            "share_count": r.get::<_, Option<i32>>("share_count").unwrap_or(0),
            "author": {
                "id": r.get::<_, Option<String>>("author_id"),
                "name": r.get::<_, Option<String>>("author_name"),
                "url": r.get::<_, Option<String>>("author_url"),
                "avatar": r.get::<_, Option<String>>("author_avatar"),
            },
            "attachments": attachments,
            "comments": comments,
        }))
    }

    pub async fn get_stats(&self) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => {
                return json!({
                    "total_posts": 0,
                    "total_comments": 0,
                    "total_authors": 0,
                    "total_links": 0,
                    "groups": []
                })
            }
        };

        let total_posts: i64 = client
            .query_one(
                "SELECT COUNT(*) FROM facebook.posts WHERE COALESCE(is_active, TRUE) = TRUE",
                &[],
            )
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let total_comments: i64 = client
            .query_one(
                "SELECT COUNT(*) FROM facebook.comments c JOIN facebook.posts p ON c.post_id = p.post_id WHERE COALESCE(p.is_active, TRUE) = TRUE",
                &[],
            )
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let total_authors: i64 = client
            .query_one("SELECT COUNT(*) FROM facebook.authors", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let total_links: i64 = client
            .query_one("SELECT COUNT(*) FROM facebook.attachments", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);

        let group_rows = client
            .query(
                "SELECT group_id, COUNT(*) as count FROM facebook.posts
                 WHERE COALESCE(is_active, TRUE) = TRUE AND group_id IS NOT NULL AND group_id <> 'unknown'
                 GROUP BY group_id ORDER BY count DESC",
                &[],
            )
            .await
            .unwrap_or_default();

        let groups: Vec<Value> = group_rows
            .into_iter()
            .map(|r| {
                json!({
                    "group_id": r.get::<_, String>("group_id"),
                    "count": r.get::<_, i64>("count"),
                })
            })
            .collect();

        json!({
            "total_posts": total_posts,
            "total_comments": total_comments,
            "total_authors": total_authors,
            "total_links": total_links,
            "groups": groups,
        })
    }
}
