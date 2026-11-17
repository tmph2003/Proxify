import json
import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger("proxify.core.traffic_storage.repository")


class RequestRepository:
    """Handles all SQLite queries for captured HTTP requests.

    Migrated from PostgreSQL with FTS5 full-text search replacing tsvector.
    """

    def init_db(self, conn):
        """Create tables, indexes, and FTS5 virtual table."""
        cur = conn.cursor()

        # Main requests table (no tsvector column — FTS5 handles search)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                timestamp_epoch REAL NOT NULL,
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
                duration_ms REAL,
                is_graphql INTEGER DEFAULT 0,
                graphql_operation TEXT,
                graphql_doc_id TEXT,
                graphql_variables TEXT,
                tags TEXT DEFAULT '[]'
            );
        """)

        # B-tree indexes (same as PostgreSQL)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_method ON requests(method);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status_code);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp_epoch);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_graphql ON requests(is_graphql);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_graphql_op ON requests(graphql_operation);")

        # FTS5 virtual table for full-text search (replaces PostgreSQL tsvector + GIN)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS requests_fts USING fts5(
                url,
                request_body,
                response_body,
                graphql_operation,
                content='requests',
                content_rowid='id',
                tokenize='porter unicode61'
            );
        """)

        # Triggers to keep FTS5 in sync with the main table
        # These replace the PostgreSQL plpgsql trigger function
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS requests_ai AFTER INSERT ON requests BEGIN
                INSERT INTO requests_fts(rowid, url, request_body, response_body, graphql_operation)
                VALUES (
                    new.id,
                    COALESCE(new.url, ''),
                    CASE 
                        WHEN new.request_content_type LIKE 'text/%' 
                             OR new.request_content_type LIKE '%json%' 
                             OR new.request_content_type LIKE '%xml%'
                        THEN SUBSTR(COALESCE(new.request_body, ''), 1, 10000)
                        ELSE ''
                    END,
                    CASE 
                        WHEN new.response_content_type LIKE 'text/%' 
                             OR new.response_content_type LIKE '%json%' 
                             OR new.response_content_type LIKE '%xml%'
                        THEN SUBSTR(COALESCE(new.response_body, ''), 1, 10000)
                        ELSE ''
                    END,
                    COALESCE(new.graphql_operation, '')
                );
            END;
        """)

        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS requests_ad AFTER DELETE ON requests BEGIN
                INSERT INTO requests_fts(requests_fts, rowid, url, request_body, response_body, graphql_operation)
                VALUES (
                    'delete',
                    old.id,
                    COALESCE(old.url, ''),
                    CASE 
                        WHEN old.request_content_type LIKE 'text/%' 
                             OR old.request_content_type LIKE '%json%' 
                             OR old.request_content_type LIKE '%xml%'
                        THEN SUBSTR(COALESCE(old.request_body, ''), 1, 10000)
                        ELSE ''
                    END,
                    CASE 
                        WHEN old.response_content_type LIKE 'text/%' 
                             OR old.response_content_type LIKE '%json%' 
                             OR old.response_content_type LIKE '%xml%'
                        THEN SUBSTR(COALESCE(old.response_body, ''), 1, 10000)
                        ELSE ''
                    END,
                    COALESCE(old.graphql_operation, '')
                );
            END;
        """)

        conn.commit()
        cur.close()

    def delete_old_requests(self, conn, retention_days: int = 7, interval: Optional[str] = None) -> int:
        """Deletes requests older than the given retention period in days.

        Uses B-tree index on timestamp_epoch for O(log N) deletion.
        """
        if interval is not None:
            # Backwards compatibility: parse string interval like "3 days"
            m = re.match(r"^(\d+)", str(interval).strip())
            if m:
                retention_days = int(m.group(1))

        retention_days = max(1, int(retention_days))
        cutoff_epoch = time.time() - (retention_days * 86400.0)

        cur = conn.cursor()
        cur.execute("DELETE FROM requests WHERE timestamp_epoch < ?;", (cutoff_epoch,))
        deleted = cur.rowcount

        # Also clean up old processed payloads in core_raw_payloads if table exists
        try:
            cutoff_ts = time.time() - (retention_days * 86400.0)
            cur.execute("""
                DELETE FROM core_raw_payloads 
                WHERE processed = 1 
                  AND created_at < datetime('now', ? || ' days');
            """, (f"-{retention_days}",))
        except Exception:
            pass

        cur.close()
        return deleted

    def save_requests_batch(self, conn, batch: list, callbacks: Optional[list] = None) -> list[int]:
        """Saves a batch of requests using vectorized multi-row INSERT with RETURNING id.

        Wraps the batch write in an explicit transaction (BEGIN IMMEDIATE) to prevent
        autocommit per-row overhead, and captures generated IDs via RETURNING id.
        Callbacks are executed OUTSIDE the SQLite write transaction to prevent
        prolonged database lock holding times.
        """
        if not batch:
            return []

        row_ids: list[int] = []
        chunk_size = 500  # Well within SQLite MAX_VARIABLE_NUMBER (32766) limit (500*22=11000)

        columns = (
            "timestamp, timestamp_epoch, method, url, scheme, domain, port, "
            "path, query_string, request_headers, request_body, "
            "request_content_type, status_code, response_headers, "
            "response_body, response_content_type, response_size, "
            "duration_ms, is_graphql, graphql_operation, graphql_doc_id, "
            "graphql_variables"
        )
        row_placeholder = "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

        in_tx = getattr(conn, "in_transaction", False)
        if not in_tx:
            conn.execute("BEGIN IMMEDIATE;")

        try:
            for start in range(0, len(batch), chunk_size):
                chunk = batch[start:start + chunk_size]
                placeholders = ", ".join([row_placeholder] * len(chunk))
                query = f"INSERT INTO requests ({columns}) VALUES {placeholders} RETURNING id"
                flat_params = [val for row in chunk for val in row]

                cur = conn.cursor()
                try:
                    cur.execute(query, flat_params)
                    chunk_ids = [r[0] for r in cur.fetchall()]
                    row_ids.extend(chunk_ids)
                finally:
                    cur.close()

            if not in_tx:
                conn.commit()
        except Exception:
            if not in_tx:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise

        # Execute callbacks OUTSIDE the SQLite write lock/transaction
        if callbacks:
            for i, row_id in enumerate(row_ids):
                cb = callbacks[i] if i < len(callbacks) else None
                if cb:
                    try:
                        cb(row_id)
                    except Exception as cb_e:
                        logger.error(f"[Repository] Callback error: {cb_e}")

        return row_ids

    def save_request(self, conn, params: tuple) -> int:
        cur = conn.cursor()
        try:
            in_tx = getattr(conn, "in_transaction", False)
            cur.execute(
                """
                INSERT INTO requests (
                    timestamp, timestamp_epoch, method, url, scheme, domain, port,
                    path, query_string, request_headers, request_body,
                    request_content_type, status_code, response_headers,
                    response_body, response_content_type, response_size,
                    duration_ms, is_graphql, graphql_operation, graphql_doc_id,
                    graphql_variables
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params
            )
            row = cur.fetchone()
            row_id = row[0] if row else cur.lastrowid
            if not in_tx:
                conn.commit()
            return row_id
        finally:
            cur.close()

    def get_request(self, pool, request_id: int) -> Optional[dict]:
        read_ctx = pool.read_cursor(dict_cursor=True) if hasattr(pool, "read_cursor") else pool.cursor(dict_cursor=True)
        with read_ctx as cur:
            cur.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
            row = cur.fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def query_requests(
        self,
        pool,
        domain: Optional[str] = None,
        method: Optional[str] = None,
        status_code: Optional[int] = None,
        search: Optional[str] = None,
        graphql_only: bool = False,
        limit: int = 200,
        offset: int = 0,
        since: Optional[float] = None,
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []

        if domain:
            conditions.append("r.domain LIKE ?")
            params.append(f"%{domain}%")
        if method:
            conditions.append("r.method = ?")
            params.append(method.upper())
        if status_code is not None:
            conditions.append("r.status_code = ?")
            params.append(status_code)
        if graphql_only:
            conditions.append("r.is_graphql = 1")
        if since is not None:
            conditions.append("r.timestamp_epoch > ?")
            params.append(since)

        if search:
            # SQLite FTS5 full-text search (replaces PostgreSQL tsvector @@)
            conditions.append("r.id IN (SELECT rowid FROM requests_fts WHERE requests_fts MATCH ?)")
            params.append(search)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT r.id, r.timestamp, r.method, r.url, r.domain, r.path, r.status_code,
                   r.response_content_type, r.response_size, r.duration_ms,
                   r.is_graphql, r.graphql_operation, r.graphql_doc_id
            FROM requests r
            {where}
            ORDER BY r.id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        read_ctx = pool.read_cursor(dict_cursor=True) if hasattr(pool, "read_cursor") else pool.cursor(dict_cursor=True)
        with read_ctx as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        return [dict(row) for row in rows]

    def get_domains(self, pool, since: Optional[float] = None) -> list[dict]:
        read_ctx = pool.read_cursor(dict_cursor=True) if hasattr(pool, "read_cursor") else pool.cursor(dict_cursor=True)
        with read_ctx as cur:
            if since is not None:
                cur.execute("""
                    SELECT domain, COUNT(*) as count
                    FROM requests
                    WHERE timestamp_epoch >= ?
                    GROUP BY domain
                    ORDER BY count DESC
                """, (since,))
            else:
                cur.execute("""
                    SELECT domain, COUNT(*) as count
                    FROM requests
                    GROUP BY domain
                    ORDER BY count DESC
                """)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, pool, since: Optional[float] = None) -> dict:
        read_ctx = pool.read_cursor(dict_cursor=True) if hasattr(pool, "read_cursor") else pool.cursor(dict_cursor=True)
        with read_ctx as cur:
            if since is not None:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_requests,
                        COUNT(DISTINCT domain) as unique_domains,
                        SUM(CASE WHEN is_graphql = 1 THEN 1 ELSE 0 END) as graphql_requests,
                        SUM(response_size) as total_response_bytes,
                        MIN(timestamp) as first_capture,
                        MAX(timestamp) as last_capture
                    FROM requests
                    WHERE timestamp_epoch >= ?
                """, (since,))
            else:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_requests,
                        COUNT(DISTINCT domain) as unique_domains,
                        SUM(CASE WHEN is_graphql = 1 THEN 1 ELSE 0 END) as graphql_requests,
                        SUM(response_size) as total_response_bytes,
                        MIN(timestamp) as first_capture,
                        MAX(timestamp) as last_capture
                    FROM requests
                """)
            row = cur.fetchone()
        return dict(row) if row else {}

    def get_requests_for_export(
        self, pool, ids: Optional[list[int]] = None, **filters
    ) -> list[dict]:
        read_ctx = pool.read_cursor(dict_cursor=True) if hasattr(pool, "read_cursor") else pool.cursor(dict_cursor=True)
        with read_ctx as cur:
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                cur.execute(
                    f"SELECT * FROM requests WHERE id IN ({placeholders}) ORDER BY id",
                    tuple(ids),
                )
                rows = cur.fetchall()
            else:
                conditions = []
                params = []

                if filters.get("domain"):
                    conditions.append("domain LIKE ?")
                    params.append(f"%{filters['domain']}%")
                if filters.get("method"):
                    conditions.append("method = ?")
                    params.append(filters["method"].upper())
                if filters.get("graphql_only"):
                    conditions.append("is_graphql = 1")
                if filters.get("status_code") is not None:
                    conditions.append("status_code = ?")
                    params.append(filters["status_code"])

                where = ""
                if conditions:
                    where = "WHERE " + " AND ".join(conditions)

                limit = filters.get("limit", 200)
                cur.execute(
                    f"SELECT * FROM requests {where} ORDER BY id DESC LIMIT ?",
                    tuple(params + [limit]),
                )
                rows = cur.fetchall()

        return [self._row_to_dict(row) for row in rows]

    def delete_requests(self, pool, ids: Optional[list[int]] = None):
        with pool.cursor() as cur:
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                cur.execute(
                    f"DELETE FROM requests WHERE id IN ({placeholders})", tuple(ids)
                )
            else:
                cur.execute("DELETE FROM requests")

    def _row_to_dict(self, row: dict) -> dict:
        """Convert a dict to a parsed dict, parsing JSON fields."""
        d = dict(row)
        for field in ("request_headers", "response_headers", "tags"):
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        # Remove search_vector if present (legacy compat)
        if "search_vector" in d:
            del d["search_vector"]
        return d
