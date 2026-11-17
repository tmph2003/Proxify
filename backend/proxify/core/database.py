import asyncio
import aiosqlite
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("proxify.core.database")


from proxify.utils.compat import get_application_base_dir, get_default_db_path

_DEFAULT_DB_PATH = get_default_db_path()


class DatabaseManager:
    """Manages the aiosqlite connection and core tables.

    Replaces the old asyncpg-based DatabaseManager.
    Provides a pool-like interface via a single aiosqlite connection
    wrapped in an asyncio.Lock for write serialization.
    """
    def __init__(self):
        self.pool: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._db_path: str = _DEFAULT_DB_PATH

    async def connect(self, dsn: str = None, min_size: int = 5, max_size: int = 20,
                      max_retries: int = 5, retry_interval: float = 2.0):
        """Initializes the aiosqlite connection with auto-recovery retries.

        Args:
            dsn: Database path (for SQLite, this is the file path).
                 Accepts old PostgreSQL DSN format for backward compatibility
                 but ignores it and uses PROXIFY_DB_PATH env var instead.
        """
        # Parse DSN: if it's a PostgreSQL URL, ignore it and use file path
        if dsn and dsn.startswith("postgresql://"):
            logger.info(f"[DB] Ignoring PostgreSQL DSN, using SQLite: {self._db_path}")
        elif dsn:
            self._db_path = dsn

        logger.info(f"Connecting to SQLite database: {self._db_path}")

        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        for attempt in range(1, max_retries + 1):
            try:
                self.pool = await aiosqlite.connect(
                    self._db_path,
                    timeout=30.0,
                )
                # Enable WAL mode for concurrent reads
                await self.pool.execute("PRAGMA journal_mode=WAL;")
                await self.pool.execute("PRAGMA synchronous=NORMAL;")
                await self.pool.execute("PRAGMA busy_timeout=5000;")
                await self.pool.execute("PRAGMA foreign_keys=ON;")
                await self.pool.execute("PRAGMA cache_size=-64000;")
                await self.pool.execute("PRAGMA temp_store=MEMORY;")
                await self.pool.execute("PRAGMA mmap_size=268435456;")

                await self._init_core_schema()
                logger.info("SQLite database established and core schema verified.")
                return
            except Exception as e:
                logger.warning(f"Database connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(retry_interval)
                else:
                    raise

    async def disconnect(self):
        """Closes the aiosqlite connection."""
        if self.pool:
            logger.info("Closing SQLite database...")
            await self.pool.close()
            self.pool = None

    async def _init_core_schema(self):
        """Creates the raw_payloads table for offline processing.

        Note: SQLite has no schema concept, so 'core.' prefix is removed.
        Table name is prefixed with 'core_' for namespacing.
        """
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS core_raw_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic VARCHAR(255) NOT NULL,
                raw_data TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                processed INTEGER DEFAULT 0
            );
        """)

        # Index for the background worker to quickly find unprocessed payloads
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_payloads_processed
            ON core_raw_payloads(processed);
        """)
        await self.pool.commit()

    def acquire(self) -> "_ConnectionWrapper":
        """Context manager that mimics asyncpg pool.acquire().

        Returns an async context manager wrapper supporting fetch/execute/executemany
        with SQLite syntax.
        """
        if self.pool is None:
            raise ConnectionError("SQLite database is not connected")
        return _ConnectionWrapper(self.pool, self._lock)


class _ConnectionWrapper:
    """Wraps aiosqlite.Connection to provide an asyncpg-compatible API.

    Supports:
        async with db_manager.acquire() as conn:
            rows = await conn.fetch("SELECT ...")
            await conn.execute("INSERT ...")
    """
    def __init__(self, conn: aiosqlite.Connection, lock: asyncio.Lock):
        self._conn = conn
        self._lock = lock

    async def __aenter__(self):
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()

    async def fetch(self, query: str, *args) -> list:
        """Fetch all rows as list of dicts (asyncpg-compatible)."""
        self._conn.row_factory = aiosqlite.Row
        cursor = await self._conn.execute(query, args if args else None)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def fetchval(self, query: str, *args):
        """Fetch a single value (first column of first row)."""
        cursor = await self._conn.execute(query, args if args else None)
        row = await cursor.fetchone()
        return row[0] if row else None

    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """Fetch a single row as dict."""
        self._conn.row_factory = aiosqlite.Row
        cursor = await self._conn.execute(query, args if args else None)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def execute(self, query: str, *args):
        """Execute a query."""
        await self._conn.execute(query, args if args else None)
        await self._conn.commit()

    async def executemany(self, query: str, args_list):
        """Execute a query for each set of args."""
        await self._conn.executemany(query, args_list)
        await self._conn.commit()

    async def transaction(self):
        """Return a dummy transaction context (SQLite auto-commits)."""
        return _DummyTransaction()


class _DummyTransaction:
    """No-op transaction context for API compatibility."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
