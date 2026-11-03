use deadpool_postgres::Pool;
use serde_json::{json, Value};
use std::sync::Arc;
use tracing::info;

pub struct ZaloStorage {
    pool: Pool,
}

impl ZaloStorage {
    pub fn new(pool: Pool) -> Arc<Self> {
        Arc::new(Self { pool })
    }

    pub async fn init_schema(&self) -> Result<(), String> {
        let client = self
            .pool
            .get()
            .await
            .map_err(|e| format!("Zalo DB connection error: {}", e))?;

        client
            .batch_execute(
                r#"
                CREATE SCHEMA IF NOT EXISTS zalo;

                CREATE TABLE IF NOT EXISTS zalo.groups (
                    group_id VARCHAR(255) PRIMARY KEY,
                    display_name TEXT DEFAULT '',
                    total_member INTEGER DEFAULT 0,
                    avatar TEXT DEFAULT '',
                    raw_data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS zalo.users (
                    user_id VARCHAR(255) PRIMARY KEY,
                    global_id VARCHAR(255) DEFAULT '',
                    display_name TEXT DEFAULT '',
                    avatar TEXT DEFAULT '',
                    phone VARCHAR(50) DEFAULT '',
                    raw_data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS zalo.group_members (
                    group_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_gm_group ON zalo.group_members(group_id);
                CREATE INDEX IF NOT EXISTS idx_gm_user ON zalo.group_members(user_id);

                CREATE TABLE IF NOT EXISTS zalo.scan_jobs (
                    id SERIAL PRIMARY KEY,
                    link TEXT NOT NULL,
                    group_id VARCHAR(255),
                    status VARCHAR(50) DEFAULT 'pending',
                    members_found INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                );
                "#,
            )
            .await
            .map_err(|e| format!("Zalo schema init failed: {}", e))?;

        info!("[ZaloStorage] Schema 'zalo' initialized.");
        Ok(())
    }

    pub async fn upsert_groups(&self, groups: &[Value]) -> usize {
        if groups.is_empty() {
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

        let mut count = 0;
        for g in groups {
            let gid = g.get("group_id").and_then(|v| v.as_str()).unwrap_or("");
            if gid.is_empty() {
                continue;
            }
            let name = g
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown Group");
            let avatar = g.get("avatar").and_then(|v| v.as_str()).unwrap_or("");
            let total_member = g.get("total_member").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let raw_str = g
                .get("raw_json")
                .map(|v| v.to_string())
                .unwrap_or_else(|| "{}".to_string());

            let _ = tx
                .execute(
                    r#"
                    INSERT INTO zalo.groups (
                        group_id, display_name, total_member, avatar, raw_data, updated_at
                    ) VALUES ($1, $2, $3, $4, $5::text::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (group_id) DO UPDATE SET
                        display_name = CASE WHEN EXCLUDED.display_name <> 'Unknown Group' THEN EXCLUDED.display_name ELSE zalo.groups.display_name END,
                        avatar = CASE WHEN EXCLUDED.avatar <> '' THEN EXCLUDED.avatar ELSE zalo.groups.avatar END,
                        total_member = CASE WHEN EXCLUDED.total_member > 0 THEN EXCLUDED.total_member ELSE zalo.groups.total_member END,
                        raw_data = COALESCE(zalo.groups.raw_data, '{}'::jsonb) || EXCLUDED.raw_data,
                        updated_at = CURRENT_TIMESTAMP
                    "#,
                    &[&gid, &name, &total_member, &avatar, &raw_str],
                )
                .await;
            count += 1;
        }

        let _ = tx.commit().await;
        count
    }

    pub async fn upsert_users(&self, users: &[Value]) -> usize {
        if users.is_empty() {
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

        let mut count = 0;
        for u in users {
            let uid = u.get("user_id").and_then(|v| v.as_str()).unwrap_or("");
            if uid.is_empty() {
                continue;
            }
            let display_name = u
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown");
            let avatar = u.get("avatar").and_then(|v| v.as_str()).unwrap_or("");
            let phone = u.get("phone_number").and_then(|v| v.as_str()).unwrap_or("");
            let global_id = u.get("global_id").and_then(|v| v.as_str()).unwrap_or("");
            let raw_str = u
                .get("raw_json")
                .map(|v| v.to_string())
                .unwrap_or_else(|| "{}".to_string());

            let _ = tx
                .execute(
                    r#"
                    INSERT INTO zalo.users (
                        user_id, global_id, display_name, avatar, phone, raw_data, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6::text::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        display_name = CASE WHEN EXCLUDED.display_name <> 'Unknown' THEN EXCLUDED.display_name ELSE zalo.users.display_name END,
                        avatar = CASE WHEN EXCLUDED.avatar <> '' THEN EXCLUDED.avatar ELSE zalo.users.avatar END,
                        phone = CASE WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone ELSE zalo.users.phone END,
                        global_id = CASE WHEN EXCLUDED.global_id <> '' THEN EXCLUDED.global_id ELSE zalo.users.global_id END,
                        raw_data = COALESCE(zalo.users.raw_data, '{}'::jsonb) || EXCLUDED.raw_data,
                        updated_at = CURRENT_TIMESTAMP
                    "#,
                    &[&uid, &global_id, &display_name, &avatar, &phone, &raw_str],
                )
                .await;
            count += 1;
        }

        let _ = tx.commit().await;
        count
    }

    pub async fn upsert_group_members(&self, memberships: &[Value]) -> usize {
        if memberships.is_empty() {
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

        let mut count = 0;
        for m in memberships {
            let gid = m.get("group_id").and_then(|v| v.as_str()).unwrap_or("");
            let uid = m.get("user_id").and_then(|v| v.as_str()).unwrap_or("");
            if gid.is_empty() || uid.is_empty() {
                continue;
            }
            let _ = tx
                .execute(
                    r#"
                    INSERT INTO zalo.group_members (group_id, user_id, joined_at)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (group_id, user_id) DO NOTHING
                    "#,
                    &[&gid, &uid],
                )
                .await;
            count += 1;
        }

        let _ = tx.commit().await;
        count
    }

    pub async fn get_groups(&self, search: Option<&str>, limit: i64, offset: i64) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return json!([]),
        };

        let rows = if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            let pat = format!("%{}%", s.trim());
            client
                .query(
                    r#"
                    SELECT g.group_id, g.display_name, g.avatar, g.total_member,
                           g.updated_at::text as updated_at,
                           (SELECT COUNT(*) FROM zalo.group_members gm WHERE gm.group_id = g.group_id) as captured_members
                    FROM zalo.groups g
                    WHERE g.display_name ILIKE $1 OR g.group_id ILIKE $1
                    ORDER BY g.total_member DESC, g.updated_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                    &[&pat, &limit, &offset],
                )
                .await
                .unwrap_or_default()
        } else {
            client
                .query(
                    r#"
                    SELECT g.group_id, g.display_name, g.avatar, g.total_member,
                           g.updated_at::text as updated_at,
                           (SELECT COUNT(*) FROM zalo.group_members gm WHERE gm.group_id = g.group_id) as captured_members
                    FROM zalo.groups g
                    ORDER BY g.total_member DESC, g.updated_at DESC
                    LIMIT $1 OFFSET $2
                    "#,
                    &[&limit, &offset],
                )
                .await
                .unwrap_or_default()
        };

        let items: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                let dname: Option<String> = r.get("display_name");
                let cap_mems: i64 = r.get::<_, Option<i64>>("captured_members").unwrap_or(0);
                json!({
                    "group_id": r.get::<_, String>("group_id"),
                    "name": dname.clone().unwrap_or_default(),
                    "display_name": dname.unwrap_or_default(),
                    "avatar": r.get::<_, Option<String>>("avatar"),
                    "total_member": r.get::<_, Option<i32>>("total_member").unwrap_or(0),
                    "captured_members": cap_mems,
                    "db_member_count": cap_mems,
                    "updated_at": r.get::<_, Option<String>>("updated_at"),
                })
            })
            .collect();

        Value::Array(items)
    }

    pub async fn get_group_members(
        &self,
        group_id: &str,
        search: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Vec<Value> {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };

        let m_rows = if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            let pat = format!("%{}%", s.trim());
            client
                .query(
                    r#"
                    SELECT gm.user_id, gm.joined_at::text as joined_at,
                           COALESCE(u.display_name, 'Unknown Profile') as display_name,
                           u.avatar, u.phone, u.global_id, u.updated_at::text as updated_at
                    FROM zalo.group_members gm
                    LEFT JOIN zalo.users u ON gm.user_id = u.user_id
                    WHERE gm.group_id = $1 AND (
                        gm.user_id ILIKE $2 OR u.display_name ILIKE $2 OR u.phone ILIKE $2
                    )
                    ORDER BY u.display_name ASC NULLS LAST
                    LIMIT $3 OFFSET $4
                    "#,
                    &[&group_id, &pat, &limit, &offset],
                )
                .await
                .unwrap_or_default()
        } else {
            client
                .query(
                    r#"
                    SELECT gm.user_id, gm.joined_at::text as joined_at,
                           COALESCE(u.display_name, 'Unknown Profile') as display_name,
                           u.avatar, u.phone, u.global_id, u.updated_at::text as updated_at
                    FROM zalo.group_members gm
                    LEFT JOIN zalo.users u ON gm.user_id = u.user_id
                    WHERE gm.group_id = $1
                    ORDER BY u.display_name ASC NULLS LAST
                    LIMIT $2 OFFSET $3
                    "#,
                    &[&group_id, &limit, &offset],
                )
                .await
                .unwrap_or_default()
        };

        m_rows
            .into_iter()
            .map(|r| {
                let phone: Option<String> = r.get("phone");
                json!({
                    "user_id": r.get::<_, String>("user_id"),
                    "role": "MEMBER",
                    "joined_at": r.get::<_, Option<String>>("joined_at"),
                    "display_name": r.get::<_, String>("display_name"),
                    "avatar": r.get::<_, Option<String>>("avatar"),
                    "phone": phone.clone(),
                    "phone_number": phone,
                    "global_id": r.get::<_, Option<String>>("global_id"),
                    "updated_at": r.get::<_, Option<String>>("updated_at"),
                })
            })
            .collect()
    }

    pub async fn export_members_csv(&self, group_id: &str) -> String {
        let members = self.get_group_members(group_id, None, 100_000, 0).await;
        let mut out = String::from("user_id,display_name,global_id,phone,updated_at\n");
        for m in members {
            let uid = m.get("user_id").and_then(|v| v.as_str()).unwrap_or("");
            let name = m
                .get("display_name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .replace('"', "\"\"");
            let gid = m.get("global_id").and_then(|v| v.as_str()).unwrap_or("");
            let phone = m.get("phone").and_then(|v| v.as_str()).unwrap_or("");
            let upd = m.get("updated_at").and_then(|v| v.as_str()).unwrap_or("");
            out.push_str(&format!(
                "\"{}\",\"{}\",\"{}\",\"{}\",\"{}\"\n",
                uid, name, gid, phone, upd
            ));
        }
        out
    }

    pub async fn get_jobs(&self, limit: i64) -> Vec<Value> {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };
        let rows = client
            .query(
                r#"
                SELECT id, link, group_id, status, members_found, error_message,
                       created_at::text as created_at,
                       started_at::text as started_at,
                       completed_at::text as completed_at
                FROM zalo.scan_jobs
                ORDER BY id DESC
                LIMIT $1
                "#,
                &[&limit],
            )
            .await
            .unwrap_or_default();

        rows.into_iter()
            .map(|r| {
                json!({
                    "id": r.get::<_, i32>("id"),
                    "link": r.get::<_, String>("link"),
                    "group_id": r.get::<_, Option<String>>("group_id"),
                    "status": r.get::<_, Option<String>>("status").unwrap_or_else(|| "pending".to_string()),
                    "members_found": r.get::<_, Option<i32>>("members_found").unwrap_or(0),
                    "error_message": r.get::<_, Option<String>>("error_message"),
                    "created_at": r.get::<_, Option<String>>("created_at"),
                    "started_at": r.get::<_, Option<String>>("started_at"),
                    "completed_at": r.get::<_, Option<String>>("completed_at"),
                })
            })
            .collect()
    }

    pub async fn create_job(&self, link: &str, status: &str) -> Option<i32> {
        let client = self.pool.get().await.ok()?;
        let row = client
            .query_opt(
                r#"
                INSERT INTO zalo.scan_jobs (link, status, started_at)
                VALUES ($1, $2, CASE WHEN $2 = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END)
                RETURNING id
                "#,
                &[&link, &status],
            )
            .await
            .ok()??;
        Some(row.get(0))
    }

    pub async fn cancel_job(&self, job_id: i32) -> bool {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return false,
        };
        client
            .execute(
                r#"
                UPDATE zalo.scan_jobs
                SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP, error_message = 'User cancelled'
                WHERE id = $1
                "#,
                &[&job_id],
            )
            .await
            .is_ok()
    }

    pub async fn get_group_detail(
        &self,
        group_id: &str,
        search: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Option<Value> {
        let client = self.pool.get().await.ok()?;
        let g_row = client
            .query_opt(
                "SELECT group_id, display_name, avatar, total_member, updated_at::text as updated_at
                 FROM zalo.groups WHERE group_id = $1",
                &[&group_id],
            )
            .await
            .ok()??;

        let dname: Option<String> = g_row.get("display_name");
        let group_info = json!({
            "group_id": g_row.get::<_, String>("group_id"),
            "name": dname.clone().unwrap_or_default(),
            "display_name": dname.unwrap_or_default(),
            "avatar": g_row.get::<_, Option<String>>("avatar"),
            "total_member": g_row.get::<_, Option<i32>>("total_member").unwrap_or(0),
            "updated_at": g_row.get::<_, Option<String>>("updated_at"),
        });

        let (total_members, m_rows) = if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            let pat = format!("%{}%", s.trim());
            let tot: i64 = client
                .query_one(
                    r#"
                    SELECT COUNT(*)
                    FROM zalo.group_members gm
                    LEFT JOIN zalo.users u ON gm.user_id = u.user_id
                    WHERE gm.group_id = $1 AND (
                        gm.user_id ILIKE $2 OR u.display_name ILIKE $2 OR u.phone ILIKE $2
                    )
                    "#,
                    &[&group_id, &pat],
                )
                .await
                .map(|r| r.get(0))
                .unwrap_or(0);
            let rows = client
                .query(
                    r#"
                    SELECT gm.user_id, gm.joined_at::text as joined_at,
                           COALESCE(u.display_name, 'Unknown Profile') as display_name,
                           u.avatar, u.phone, u.global_id
                    FROM zalo.group_members gm
                    LEFT JOIN zalo.users u ON gm.user_id = u.user_id
                    WHERE gm.group_id = $1 AND (
                        gm.user_id ILIKE $2 OR u.display_name ILIKE $2 OR u.phone ILIKE $2
                    )
                    ORDER BY u.display_name ASC NULLS LAST
                    LIMIT $3 OFFSET $4
                    "#,
                    &[&group_id, &pat, &limit, &offset],
                )
                .await
                .unwrap_or_default();
            (tot, rows)
        } else {
            let tot: i64 = client
                .query_one(
                    "SELECT COUNT(*) FROM zalo.group_members WHERE group_id = $1",
                    &[&group_id],
                )
                .await
                .map(|r| r.get(0))
                .unwrap_or(0);
            let rows = client
                .query(
                    r#"
                    SELECT gm.user_id, gm.joined_at::text as joined_at,
                           COALESCE(u.display_name, 'Unknown Profile') as display_name,
                           u.avatar, u.phone, u.global_id
                    FROM zalo.group_members gm
                    LEFT JOIN zalo.users u ON gm.user_id = u.user_id
                    WHERE gm.group_id = $1
                    ORDER BY u.display_name ASC NULLS LAST
                    LIMIT $2 OFFSET $3
                    "#,
                    &[&group_id, &limit, &offset],
                )
                .await
                .unwrap_or_default();
            (tot, rows)
        };

        let members: Vec<Value> = m_rows
            .into_iter()
            .map(|r| {
                let phone: Option<String> = r.get("phone");
                json!({
                    "user_id": r.get::<_, String>("user_id"),
                    "role": "MEMBER",
                    "joined_at": r.get::<_, Option<String>>("joined_at"),
                    "display_name": r.get::<_, String>("display_name"),
                    "avatar": r.get::<_, Option<String>>("avatar"),
                    "phone": phone.clone(),
                    "phone_number": phone,
                    "global_id": r.get::<_, Option<String>>("global_id"),
                })
            })
            .collect();

        Some(json!({
            "group": group_info,
            "total_members": total_members,
            "members": members,
        }))
    }

    pub async fn get_users(&self, search: Option<&str>, limit: i64, offset: i64) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => return json!({ "total": 0, "users": [] }),
        };

        let (total, rows) = if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            let pat = format!("%{}%", s.trim());
            let tot: i64 = client
                .query_one(
                    "SELECT COUNT(*) FROM zalo.users WHERE display_name ILIKE $1 OR phone ILIKE $1 OR user_id ILIKE $1",
                    &[&pat],
                )
                .await
                .map(|r| r.get(0))
                .unwrap_or(0);
            let r = client
                .query(
                    r#"
                    SELECT u.user_id, u.display_name, u.avatar, u.phone, u.global_id, u.updated_at::text as updated_at,
                           (SELECT COUNT(*) FROM zalo.group_members gm WHERE gm.user_id = u.user_id) as group_count
                    FROM zalo.users u
                    WHERE u.display_name ILIKE $1 OR u.phone ILIKE $1 OR u.user_id ILIKE $1
                    ORDER BY u.updated_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                    &[&pat, &limit, &offset],
                )
                .await
                .unwrap_or_default();
            (tot, r)
        } else {
            let tot: i64 = client
                .query_one("SELECT COUNT(*) FROM zalo.users", &[])
                .await
                .map(|r| r.get(0))
                .unwrap_or(0);
            let r = client
                .query(
                    r#"
                    SELECT u.user_id, u.display_name, u.avatar, u.phone, u.global_id, u.updated_at::text as updated_at,
                           (SELECT COUNT(*) FROM zalo.group_members gm WHERE gm.user_id = u.user_id) as group_count
                    FROM zalo.users u
                    ORDER BY u.updated_at DESC
                    LIMIT $1 OFFSET $2
                    "#,
                    &[&limit, &offset],
                )
                .await
                .unwrap_or_default();
            (tot, r)
        };

        let users: Vec<Value> = rows
            .into_iter()
            .map(|r| {
                let phone: Option<String> = r.get("phone");
                json!({
                    "user_id": r.get::<_, String>("user_id"),
                    "display_name": r.get::<_, Option<String>>("display_name").unwrap_or_default(),
                    "avatar": r.get::<_, Option<String>>("avatar"),
                    "phone": phone.clone(),
                    "phone_number": phone,
                    "global_id": r.get::<_, Option<String>>("global_id"),
                    "group_count": r.get::<_, Option<i64>>("group_count").unwrap_or(0),
                    "updated_at": r.get::<_, Option<String>>("updated_at"),
                })
            })
            .collect();

        json!({ "total": total, "users": users })
    }

    pub async fn get_stats(&self) -> Value {
        let client = match self.pool.get().await {
            Ok(c) => c,
            Err(_) => {
                return json!({
                    "groups": 0,
                    "users": 0,
                    "memberships": 0,
                    "scans": 0,
                    "total_groups": 0,
                    "total_users": 0,
                    "total_memberships": 0,
                    "pending_jobs": 0
                })
            }
        };
        let total_groups: i64 = client
            .query_one("SELECT COUNT(*) FROM zalo.groups", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let total_users: i64 = client
            .query_one("SELECT COUNT(*) FROM zalo.users", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let total_memberships: i64 = client
            .query_one("SELECT COUNT(*) FROM zalo.group_members", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);
        let pending_jobs: i64 = client
            .query_one(
                "SELECT COUNT(*) FROM zalo.scan_jobs WHERE status = 'pending'",
                &[],
            )
            .await
            .map(|r| r.get(0))
            .unwrap_or(0);

        json!({
            "groups": total_groups,
            "users": total_users,
            "memberships": total_memberships,
            "scans": pending_jobs,
            "total_groups": total_groups,
            "total_users": total_users,
            "total_memberships": total_memberships,
            "pending_jobs": pending_jobs,
        })
    }
}
