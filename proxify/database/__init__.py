"""
Database Package — shared connection pool cho toàn bộ ứng dụng.

Mỗi platform (zalo, facebook, ...) tự quản lý database riêng
nhưng dùng chung connection pool này.

Usage:
    from proxify.database import pool

    # Dùng trực tiếp
    with pool.cursor() as cur:
        cur.execute("SELECT 1")

    # Hoặc từ platform module
    from proxify.platforms.zalo import zalo_db
    zalo_db.groups.upsert(...)
"""

from .connection import DatabasePool

# Shared connection pool — singleton
pool = DatabasePool()

__all__ = ["pool", "DatabasePool"]
