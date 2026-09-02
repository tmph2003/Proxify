"""
ZaloDatabase — Facade class cho tất cả Zalo database operations.

Tự động tạo schema `zalo` và tất cả bảng khi khởi tạo.

Usage:
    from proxify.platforms.zalo import zalo_db

    zalo_db.groups.upsert(group_id, name, count, data)
    zalo_db.users.upsert(user_id, global_id, name, avatar, phone, data)
    zalo_db.memberships.link_members(group_id, [uid1, uid2])
    zalo_db.jobs.create(link)
    stats = zalo_db.get_stats()
"""

import logging

from proxify.database import pool as shared_pool
from .repository import (
    GroupRepository,
    MembershipRepository,
    ScanJobRepository,
    StatsRepository,
    UserRepository,
    SCHEMA,
)

logger = logging.getLogger("proxify")


class ZaloDatabase:
    """Facade — single entry point cho Zalo database.

    Sử dụng schema `zalo` trong PostgreSQL.
    Tự động tạo schema + tables khi khởi tạo.
    """

    def __init__(self):
        self._pool = shared_pool

        # Repositories
        self.groups = GroupRepository(self._pool)
        self.users = UserRepository(self._pool)
        self.memberships = MembershipRepository(self._pool)
        self.jobs = ScanJobRepository(self._pool)
        self._stats = StatsRepository(self._pool)

        # Auto-init will be called manually to avoid blocking imports
        # self._init_schema()
        # self._init_tables()
        self._init_done = False

    def init_db(self):
        if not self._init_done:
            self._init_schema()
            self._init_tables()
            self._init_done = True

    def _init_schema(self) -> None:
        """Tạo schema `zalo` nếu chưa tồn tại."""
        self._pool.ensure_schema(SCHEMA)

    def _init_tables(self) -> None:
        """Tạo tất cả bảng trong schema `zalo`."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.groups (
                        group_id VARCHAR(255) PRIMARY KEY,
                        display_name TEXT DEFAULT '',
                        total_member INTEGER DEFAULT 0,
                        avatar TEXT DEFAULT '',
                        raw_data JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.users (
                        user_id VARCHAR(255) PRIMARY KEY,
                        global_id VARCHAR(255) DEFAULT '',
                        display_name TEXT DEFAULT '',
                        avatar TEXT DEFAULT '',
                        phone VARCHAR(50) DEFAULT '',
                        raw_data JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.group_members (
                        group_id VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (group_id, user_id)
                    )
                """)
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_gm_group
                    ON {SCHEMA}.group_members(group_id)
                """)
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_gm_user
                    ON {SCHEMA}.group_members(user_id)
                """)

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.scan_jobs (
                        id SERIAL PRIMARY KEY,
                        link TEXT NOT NULL,
                        group_id VARCHAR(255),
                        status VARCHAR(50) DEFAULT 'pending',
                        members_found INTEGER DEFAULT 0,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """)

                logger.info(f"[ZALO] Tables initialized in schema '{SCHEMA}'.")
        except Exception as e:
            logger.error(f"[ZALO] Error initializing tables: {e}")

    def get_stats(self) -> dict:
        """Shortcut cho StatsRepository.get_stats()."""
        return self._stats.get_stats()

    @property
    def pool(self):
        """Access shared pool for advanced queries."""
        return self._pool

zalo_db = ZaloDatabase()
