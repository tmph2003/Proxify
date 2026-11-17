"""
Database Connection Pool — quản lý kết nối SQLite.

Thread-safe SQLite connection manager with WAL mode.
Provides the same API surface as the old PostgreSQL DatabasePool
so consumers (RequestStorage, workers) don't need to change their
call patterns.
"""

import logging
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("proxify")


from proxify.utils.compat import get_application_base_dir, get_default_db_path

# Default database path: alongside the executable or in current working directory
_DEFAULT_DB_PATH = get_default_db_path()


class DictRow(dict):
    """dict subclass that also supports attribute-style access (row.column_name).
    Compatible with psycopg2 RealDictCursor return type.
    """
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> DictRow:
    """Row factory that returns DictRow instances."""
    fields = [column[0] for column in cursor.description]
    return DictRow(zip(fields, row))


class DatabasePool:
    """Thread-safe SQLite connection manager with WAL mode and reader pooling.

    Uses a dedicated writer connection (under self._lock) and independent
    thread-local reader connections configured with PRAGMA query_only=ON
    without acquiring self._lock, achieving zero-contention read/write concurrency.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._local = threading.local()
        self._readers_lock = threading.Lock()
        self._reader_conns: list[sqlite3.Connection] = []
        self._version: int = 0

    def _ensure_connection(self) -> sqlite3.Connection | None:
        """Lazily create the SQLite writer connection with WAL mode."""
        with self._lock:
            if self._conn is None:
                try:
                    resolved_path = self._db_path or get_default_db_path()
                    db_dir = os.path.dirname(resolved_path)
                    if db_dir:
                        os.makedirs(db_dir, exist_ok=True)

                    self._conn = sqlite3.connect(
                        resolved_path,
                        check_same_thread=False,
                        timeout=30.0,
                    )
                    # Enable WAL mode and optimized PRAGMAs for writer
                    self._conn.execute("PRAGMA journal_mode=WAL;")
                    self._conn.execute("PRAGMA synchronous=NORMAL;")
                    self._conn.execute("PRAGMA busy_timeout=5000;")
                    self._conn.execute("PRAGMA foreign_keys=ON;")
                    self._conn.execute("PRAGMA cache_size=-64000;")
                    self._conn.execute("PRAGMA temp_store=MEMORY;")
                    self._conn.execute("PRAGMA mmap_size=268435456;")
                    # Autocommit by default (matching old PostgreSQL behavior)
                    self._conn.isolation_level = None
                    logger.info(f"[DB] SQLite writer connection created: {resolved_path}")
                except Exception as e:
                    logger.error(f"[DB] Cannot open SQLite database: {e}")
                    return None
            return self._conn

    def _ensure_read_connection(self) -> sqlite3.Connection | None:
        """Get or create an independent read connection for the current thread."""
        resolved_path = self._db_path or get_default_db_path()
        if resolved_path == ":memory:":
            return self.get_connection()

        curr_version = getattr(self._local, "version", None)
        conn = getattr(self._local, "read_conn", None)

        if curr_version == self._version and conn is not None:
            return conn

        # If stale reader connection exists from prior close/reset, safely close it
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.read_conn = None

        try:
            db_dir = os.path.dirname(resolved_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            read_conn = sqlite3.connect(
                resolved_path,
                check_same_thread=False,
                timeout=5.0,
            )
            read_conn.execute("PRAGMA query_only = ON;")
            read_conn.execute("PRAGMA busy_timeout = 5000;")
            read_conn.execute("PRAGMA cache_size = -64000;")
            read_conn.execute("PRAGMA temp_store = MEMORY;")
            read_conn.execute("PRAGMA mmap_size = 268435456;")
            read_conn.isolation_level = None

            self._local.read_conn = read_conn
            self._local.version = self._version

            with self._readers_lock:
                self._reader_conns.append(read_conn)

            return read_conn
        except Exception as e:
            logger.error(f"[DB] Cannot open SQLite reader connection: {e}")
            return None

    def get_connection(self) -> sqlite3.Connection | None:
        """Get the shared writer connection (thread-safe via WAL + lock)."""
        with self._lock:
            return self._ensure_connection()

    def release_connection(self, conn) -> None:
        """No-op for SQLite (single writer connection, no pool to return to)."""
        pass

    @contextmanager
    def connection(self):
        """Context manager — get the shared writer connection.

        Usage:
            with pool.connection() as conn:
                conn.execute(...)
        """
        with self._lock:
            conn = self._ensure_connection()
            if conn is None:
                raise ConnectionError("Cannot get database connection")
            yield conn

    @contextmanager
    def read_connection(self):
        """Context manager — get an independent read connection.

        In WAL mode, readers do not block writers and writers do not block readers.
        Does not acquire self._lock, eliminating lock contention.
        """
        resolved_path = self._db_path or get_default_db_path()
        if resolved_path == ":memory:":
            with self.connection() as conn:
                yield conn
            return

        conn = self._ensure_read_connection()
        if conn is None:
            raise ConnectionError("Cannot get database read connection")
        yield conn

    @contextmanager
    def cursor(self, dict_cursor: bool = False):
        """Context manager — get a cursor from the writer connection."""
        with self.connection() as conn:
            old_factory = conn.row_factory
            if dict_cursor:
                conn.row_factory = _dict_factory
            else:
                conn.row_factory = None
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()
                conn.row_factory = old_factory

    @contextmanager
    def read_cursor(self, dict_cursor: bool = False):
        """Context manager — get a cursor from an independent read connection."""
        with self.read_connection() as conn:
            old_factory = conn.row_factory
            if dict_cursor:
                conn.row_factory = _dict_factory
            else:
                conn.row_factory = None
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()
                conn.row_factory = old_factory

    def ensure_schema(self, schema_name: str) -> None:
        """No-op for SQLite (SQLite has no schema concept).

        Args:
            schema_name: Ignored — kept for API compatibility.
        """
        logger.debug(f"[DB] Schema '{schema_name}' skipped (SQLite has no schema concept).")

    def close(self):
        """Close the SQLite writer and all reader connections."""
        with self._lock:
            self._version += 1
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

            with self._readers_lock:
                for r_conn in self._reader_conns:
                    try:
                        r_conn.close()
                    except Exception:
                        pass
                self._reader_conns.clear()

            self._local = threading.local()
