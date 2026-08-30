"""
Database Connection Pool — quản lý kết nối PostgreSQL.

Sử dụng ThreadedConnectionPool cho multi-threaded access.
Context manager tự động return connection về pool.

Shared across all platforms (zalo, facebook, etc.).
"""

import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("proxify")

DB_DSN = os.getenv("DB_DSN", "postgresql://proxify_user:proxify_pass@localhost:5432/proxify_db")


class DatabasePool:
    """Thread-safe PostgreSQL connection pool — shared across all platforms."""

    def __init__(self, dsn: str = DB_DSN, min_conn: int = 1, max_conn: int = 5):
        self._dsn = dsn
        self._min_conn = min_conn
        self._max_conn = max_conn
        self._pool: pool.ThreadedConnectionPool | None = None

    def _ensure_pool(self) -> pool.ThreadedConnectionPool | None:
        """Lazily create the connection pool."""
        if self._pool is None:
            try:
                self._pool = pool.ThreadedConnectionPool(
                    minconn=self._min_conn,
                    maxconn=self._max_conn,
                    dsn=self._dsn,
                )
                logger.info("[DB] Connection pool created.")
            except Exception as e:
                logger.error(f"[DB] Cannot connect to PostgreSQL: {e}")
                return None
        return self._pool

    def get_connection(self):
        """Get a raw connection from the pool (caller must release)."""
        p = self._ensure_pool()
        if not p:
            return None
        try:
            conn = p.getconn()
            conn.autocommit = True
            return conn
        except Exception as e:
            logger.error(f"[DB] Error getting connection: {e}")
            return None

    def release_connection(self, conn):
        """Return a connection to the pool."""
        p = self._ensure_pool()
        if p and conn:
            try:
                p.putconn(conn)
            except Exception:
                pass

    @contextmanager
    def connection(self):
        """Context manager — tự động lấy và trả connection.

        Usage:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(...)
        """
        conn = self.get_connection()
        if conn is None:
            raise ConnectionError("Cannot get database connection")
        try:
            yield conn
        finally:
            self.release_connection(conn)

    @contextmanager
    def cursor(self, dict_cursor: bool = False):
        """Context manager — lấy cursor trực tiếp.

        Usage:
            with pool.cursor(dict_cursor=True) as cur:
                cur.execute(...)
                rows = cur.fetchall()
        """
        with self.connection() as conn:
            factory = RealDictCursor if dict_cursor else None
            with conn.cursor(cursor_factory=factory) as cur:
                yield cur

    def ensure_schema(self, schema_name: str) -> None:
        """Tạo schema nếu chưa tồn tại.

        Args:
            schema_name: Tên schema (e.g., 'zalo', 'facebook')
        """
        try:
            with self.cursor() as cur:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
                logger.info(f"[DB] Schema '{schema_name}' ensured.")
        except Exception as e:
            logger.error(f"[DB] Error creating schema '{schema_name}': {e}")

    def close(self):
        """Close all connections in the pool."""
        if self._pool:
            try:
                self._pool.closeall()
            except Exception:
                pass
            self._pool = None
