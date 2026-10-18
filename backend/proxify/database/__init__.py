"""
Database Package — shared connection pool cho toàn bộ ứng dụng.

Usage:
    from proxify.database import pool

    with pool.cursor() as cur:
        cur.execute("SELECT 1")
"""

from .connection import DatabasePool

# Shared connection pool — singleton
pool = DatabasePool()

__all__ = ["pool", "DatabasePool"]
