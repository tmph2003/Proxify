"""
Zalo Repositories — CRUD cho schema `zalo` trong PostgreSQL.

Tất cả bảng sử dụng schema `zalo`:
  - zalo.groups
  - zalo.users
  - zalo.group_members
  - zalo.scan_jobs
"""

import logging
from typing import Optional

from psycopg2.extras import Json

from proxify.database import DatabasePool

logger = logging.getLogger("proxify")

# Schema name for all Zalo tables
SCHEMA = "zalo"


class GroupRepository:
    """CRUD cho bảng zalo.groups."""

    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def upsert(self, group_id: str, display_name: str = "",
               total_member: int = 0, raw_data: dict | None = None) -> None:
        """Insert hoặc update một group."""
        if not group_id:
            return
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.groups (group_id, display_name, total_member, raw_data, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (group_id)
                    DO UPDATE SET
                        display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), {SCHEMA}.groups.display_name),
                        total_member = GREATEST(EXCLUDED.total_member, {SCHEMA}.groups.total_member),
                        raw_data = EXCLUDED.raw_data,
                        updated_at = CURRENT_TIMESTAMP
                """, (group_id, display_name or '', total_member or 0, Json(raw_data or {})))
                logger.info(f"[ZALO] Upserted group {group_id} ({display_name})")
        except Exception as e:
            logger.error(f"[ZALO] Error upserting group {group_id}: {e}")

    def get_all(self, search: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """Lấy danh sách groups với member count."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                if search:
                    cur.execute(f"""
                        SELECT g.group_id, g.display_name, g.total_member, g.avatar, g.updated_at,
                               COUNT(gm.user_id) AS db_member_count
                        FROM {SCHEMA}.groups g
                        LEFT JOIN {SCHEMA}.group_members gm ON g.group_id = gm.group_id
                        WHERE g.display_name ILIKE %s OR g.group_id ILIKE %s
                        GROUP BY g.group_id
                        ORDER BY g.updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (f'%{search}%', f'%{search}%', limit, offset))
                else:
                    cur.execute(f"""
                        SELECT g.group_id, g.display_name, g.total_member, g.avatar, g.updated_at,
                               COUNT(gm.user_id) AS db_member_count
                        FROM {SCHEMA}.groups g
                        LEFT JOIN {SCHEMA}.group_members gm ON g.group_id = gm.group_id
                        GROUP BY g.group_id
                        ORDER BY g.updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (limit, offset))
                rows = cur.fetchall()
                for r in rows:
                    if r.get('updated_at'):
                        r['updated_at'] = r['updated_at'].isoformat()
                return rows
        except Exception as e:
            logger.error(f"[ZALO] Error querying groups: {e}")
            return []

    def get_members(self, group_id: str, search: str | None = None,
                    limit: int = 200, offset: int = 0) -> list[dict]:
        """Lấy danh sách thành viên của một group."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                if search:
                    cur.execute(f"""
                        SELECT u.user_id, u.global_id, u.display_name, u.avatar, u.phone, u.updated_at
                        FROM {SCHEMA}.users u
                        JOIN {SCHEMA}.group_members gm ON u.user_id = gm.user_id
                        WHERE gm.group_id = %s
                            AND (u.display_name ILIKE %s OR u.phone ILIKE %s OR u.user_id ILIKE %s)
                        ORDER BY u.display_name ASC
                        LIMIT %s OFFSET %s
                    """, (group_id, f'%{search}%', f'%{search}%', f'%{search}%', limit, offset))
                else:
                    cur.execute(f"""
                        SELECT u.user_id, u.global_id, u.display_name, u.avatar, u.phone, u.updated_at
                        FROM {SCHEMA}.users u
                        JOIN {SCHEMA}.group_members gm ON u.user_id = gm.user_id
                        WHERE gm.group_id = %s
                        ORDER BY u.display_name ASC
                        LIMIT %s OFFSET %s
                    """, (group_id, limit, offset))
                rows = cur.fetchall()
                for r in rows:
                    if r.get('updated_at'):
                        r['updated_at'] = r['updated_at'].isoformat()
                return rows
        except Exception as e:
            logger.error(f"[ZALO] Error querying members for {group_id}: {e}")
            return []

    def export_members_csv(self, group_id: str) -> str:
        """Export members thành CSV string."""
        members = self.get_members(group_id, limit=100000)
        if not members:
            return ""
        lines = ["user_id,global_id,display_name,phone,avatar"]
        for m in members:
            row = [
                m.get('user_id', ''),
                m.get('global_id', ''),
                (m.get('display_name', '') or '').replace(',', ' '),
                m.get('phone', ''),
                m.get('avatar', ''),
            ]
            lines.append(','.join(row))
        return '\n'.join(lines)


class UserRepository:
    """CRUD cho bảng zalo.users."""

    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def upsert(self, user_id: str, global_id: str = "", display_name: str = "",
               avatar: str = "", phone: str = "", raw_data: dict | None = None) -> None:
        """Insert hoặc update một user."""
        if not user_id:
            return
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.users (user_id, global_id, display_name, avatar, phone, raw_data, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        global_id = COALESCE(NULLIF(EXCLUDED.global_id, ''), {SCHEMA}.users.global_id),
                        display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), {SCHEMA}.users.display_name),
                        avatar = COALESCE(NULLIF(EXCLUDED.avatar, ''), {SCHEMA}.users.avatar),
                        phone = COALESCE(NULLIF(EXCLUDED.phone, ''), {SCHEMA}.users.phone),
                        raw_data = EXCLUDED.raw_data,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, global_id or '', display_name or '', avatar or '',
                      phone or '', Json(raw_data or {})))
        except Exception as e:
            logger.error(f"[ZALO] Error upserting user {user_id}: {e}")

    def get_all(self, search: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        """Lấy tất cả users."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                if search:
                    cur.execute(f"""
                        SELECT user_id, global_id, display_name, avatar, phone, updated_at
                        FROM {SCHEMA}.users
                        WHERE display_name ILIKE %s OR phone ILIKE %s
                              OR user_id ILIKE %s OR global_id ILIKE %s
                        ORDER BY updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%', limit, offset))
                else:
                    cur.execute(f"""
                        SELECT user_id, global_id, display_name, avatar, phone, updated_at
                        FROM {SCHEMA}.users
                        ORDER BY updated_at DESC
                        LIMIT %s OFFSET %s
                    """, (limit, offset))
                rows = cur.fetchall()
                for r in rows:
                    if r.get('updated_at'):
                        r['updated_at'] = r['updated_at'].isoformat()
                return rows
        except Exception as e:
            logger.error(f"[ZALO] Error querying users: {e}")
            return []


class MembershipRepository:
    """CRUD cho bảng zalo.group_members."""

    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def link_members(self, group_id: str, user_ids: list[str]) -> None:
        """Liên kết danh sách user_ids với group."""
        if not group_id or not user_ids:
            return
        try:
            with self._pool.cursor() as cur:
                for uid in user_ids:
                    if uid:
                        cur.execute(f"""
                            INSERT INTO {SCHEMA}.group_members (group_id, user_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                        """, (group_id, str(uid)))
        except Exception as e:
            logger.error(f"[ZALO] Error linking members for group {group_id}: {e}")


class ScanJobRepository:
    """CRUD cho bảng zalo.scan_jobs."""

    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def create(self, link: str) -> Optional[int]:
        """Tạo scan job mới. Trả về job ID."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.scan_jobs (link, status, created_at)
                    VALUES (%s, 'pending', CURRENT_TIMESTAMP)
                    RETURNING id
                """, (link,))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"[ZALO] Error creating scan job: {e}")
            return None

    def update(self, job_id: int, **kwargs) -> None:
        """Update scan job."""
        if not kwargs:
            return
        try:
            sets = []
            vals = []
            for k, v in kwargs.items():
                if v == "CURRENT_TIMESTAMP":
                    sets.append(f"{k} = CURRENT_TIMESTAMP")
                else:
                    sets.append(f"{k} = %s")
                    vals.append(v)
            vals.append(job_id)
            with self._pool.cursor() as cur:
                cur.execute(
                    f"UPDATE {SCHEMA}.scan_jobs SET {', '.join(sets)} WHERE id = %s",
                    vals
                )
        except Exception as e:
            logger.error(f"[ZALO] Error updating scan job {job_id}: {e}")

    def mark_completed_by_group(self, group_id: str) -> None:
        """Đánh dấu các jobs liên quan đến group_id đã hoàn thành."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.scan_jobs 
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP 
                    WHERE link LIKE %s AND status IN ('pending', 'running')
                """, (f"%{group_id}%",))
        except Exception as e:
            logger.error(f"[ZALO] Error marking jobs completed for group {group_id}: {e}")

    def get_all(self, limit: int = 50) -> list[dict]:
        """Lấy danh sách scan jobs gần đây."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                cur.execute(f"""
                    SELECT id, link, group_id, status, members_found, error_message,
                           created_at, started_at, completed_at
                    FROM {SCHEMA}.scan_jobs
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                for r in rows:
                    for k in ('created_at', 'started_at', 'completed_at'):
                        if r.get(k):
                            r[k] = r[k].isoformat()
                return rows
        except Exception as e:
            logger.error(f"[ZALO] Error querying scan jobs: {e}")
            return []

    def get_pending(self) -> list[dict]:
        """Lấy các jobs đang chờ xử lý."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                cur.execute(f"""
                    SELECT id, link FROM {SCHEMA}.scan_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                """)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"[ZALO] Error querying pending jobs: {e}")
            return []

    def get_running_jobs(self) -> list[dict]:
        """Lấy các jobs đang chạy (running)."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                cur.execute(f"""
                    SELECT id, link FROM {SCHEMA}.scan_jobs
                    WHERE status = 'running'
                """)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"[ZALO] Error querying running jobs: {e}")
            return []


class StatsRepository:
    """Thống kê tổng quát cho Zalo."""

    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def get_stats(self) -> dict:
        """Lấy thống kê."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.groups")
                groups = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.users")
                users = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.group_members")
                memberships = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.scan_jobs")
                scans = cur.fetchone()[0]
                return {
                    "groups": groups,
                    "users": users,
                    "memberships": memberships,
                    "scans": scans,
                }
        except Exception as e:
            logger.error(f"[ZALO] Error getting stats: {e}")
            return {"groups": 0, "users": 0, "memberships": 0, "scans": 0}
