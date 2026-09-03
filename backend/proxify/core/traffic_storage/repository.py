import json
import logging
from typing import Any, Optional
from psycopg2.extras import execute_values

logger = logging.getLogger("proxify.core.traffic_storage.repository")

class RequestRepository:
    """Handles all PostgreSQL queries for captured HTTP requests."""

    def init_db(self, conn):
        """Create tables and indexes."""
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    timestamp_epoch DOUBLE PRECISION NOT NULL,
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
                    duration_ms DOUBLE PRECISION,
                    is_graphql INTEGER DEFAULT 0,
                    graphql_operation TEXT,
                    graphql_doc_id TEXT,
                    graphql_variables TEXT,
                    tags TEXT DEFAULT '[]',
                    search_vector tsvector
                );

                CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain);
                CREATE INDEX IF NOT EXISTS idx_requests_method ON requests(method);
                CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status_code);
                CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp_epoch);
                CREATE INDEX IF NOT EXISTS idx_requests_graphql ON requests(is_graphql);
                CREATE INDEX IF NOT EXISTS idx_requests_graphql_op ON requests(graphql_operation);
                CREATE INDEX IF NOT EXISTS idx_requests_search ON requests USING GIN(search_vector);
            """)

            # Postgres function and trigger for FTS
            cur.execute("""
                CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
                BEGIN
                    IF (NEW.response_content_type LIKE 'text/%' OR NEW.response_content_type LIKE '%json%' OR NEW.response_content_type LIKE '%xml%') THEN
                        NEW.search_vector := 
                            setweight(to_tsvector('english', coalesce(NEW.url, '')), 'A') ||
                            setweight(to_tsvector('english', substring(coalesce(NEW.request_body, ''), 1, 10000)), 'B') ||
                            setweight(to_tsvector('english', substring(coalesce(NEW.response_body, ''), 1, 10000)), 'C') ||
                            setweight(to_tsvector('english', coalesce(NEW.graphql_operation, '')), 'A');
                    ELSE
                        NEW.search_vector := 
                            setweight(to_tsvector('english', coalesce(NEW.url, '')), 'A') ||
                            setweight(to_tsvector('english', coalesce(NEW.graphql_operation, '')), 'A');
                    END IF;
                    RETURN NEW;
                END
                $$ LANGUAGE plpgsql;
            """)
            
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'tsvectorupdate') THEN
                        CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
                        ON requests FOR EACH ROW EXECUTE FUNCTION update_search_vector();
                    END IF;
                END
                $$;
            """)
        conn.commit()

    def delete_old_requests(self, conn, interval: str = '3 days') -> int:
        """Deletes requests older than the given interval."""
        with conn.cursor() as cur:
            cur.execute(f"""
                DELETE FROM requests 
                WHERE timestamp_epoch < EXTRACT(EPOCH FROM NOW() - INTERVAL '{interval}');
            """)
            return cur.rowcount

    def save_requests_batch(self, conn, batch: list, callbacks: list) -> None:
        """Saves a batch of requests."""
        with conn.cursor() as cur:
            query = """
                INSERT INTO requests (
                    timestamp, timestamp_epoch, method, url, scheme, domain, port,
                    path, query_string, request_headers, request_body,
                    request_content_type, status_code, response_headers,
                    response_body, response_content_type, response_size,
                    duration_ms, is_graphql, graphql_operation, graphql_doc_id,
                    graphql_variables
                ) VALUES %s
                RETURNING id
            """
            res = execute_values(cur, query, batch, fetch=True)
            
            for row_id, cb in zip(res, callbacks):
                if cb:
                    try:
                        cb(row_id[0])
                    except Exception as cb_e:
                        logger.error(f"[Repository] Callback error: {cb_e}")

    def save_request(self, conn, params: tuple) -> int:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO requests (
                    timestamp, timestamp_epoch, method, url, scheme, domain, port,
                    path, query_string, request_headers, request_body,
                    request_content_type, status_code, response_headers,
                    response_body, response_content_type, response_size,
                    duration_ms, is_graphql, graphql_operation, graphql_doc_id,
                    graphql_variables
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                params
            )
            return cur.fetchone()[0]

    def get_request(self, pool, request_id: int) -> Optional[dict]:
        with pool.cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM requests WHERE id = %s", (request_id,))
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
            conditions.append("domain LIKE %s")
            params.append(f"%{domain}%")
        if method:
            conditions.append("method = %s")
            params.append(method.upper())
        if status_code is not None:
            conditions.append("status_code = %s")
            params.append(status_code)
        if graphql_only:
            conditions.append("is_graphql = 1")
        if since is not None:
            conditions.append("timestamp_epoch > %s")
            params.append(since)

        if search:
            # Postgres FTS
            conditions.append("search_vector @@ plainto_tsquery('english', %s)")
            params.append(search)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT id, timestamp, method, url, domain, path, status_code,
                   response_content_type, response_size, duration_ms,
                   is_graphql, graphql_operation, graphql_doc_id
            FROM requests
            {where}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        with pool.cursor(dict_cursor=True) as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            
        return [dict(row) for row in rows]

    def get_domains(self, pool, since: Optional[float] = None) -> list[dict]:
        with pool.cursor(dict_cursor=True) as cur:
            where = "WHERE timestamp_epoch >= %s" if since is not None else ""
            params = (since,) if since is not None else ()
            cur.execute(f"""
                SELECT domain, COUNT(*) as count
                FROM requests
                {where}
                GROUP BY domain
                ORDER BY count DESC
            """, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, pool, since: Optional[float] = None) -> dict:
        with pool.cursor(dict_cursor=True) as cur:
            where = "WHERE timestamp_epoch >= %s" if since is not None else ""
            params = (since,) if since is not None else ()
            cur.execute(f"""
                SELECT
                    COUNT(*) as total_requests,
                    COUNT(DISTINCT domain) as unique_domains,
                    SUM(CASE WHEN is_graphql = 1 THEN 1 ELSE 0 END) as graphql_requests,
                    SUM(response_size) as total_response_bytes,
                    MIN(timestamp) as first_capture,
                    MAX(timestamp) as last_capture
                FROM requests
                {where}
            """, params)
            row = cur.fetchone()
        return dict(row) if row else {}

    def get_requests_for_export(
        self, pool, ids: Optional[list[int]] = None, **filters
    ) -> list[dict]:
        with pool.cursor(dict_cursor=True) as cur:
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(
                    f"SELECT * FROM requests WHERE id IN ({placeholders}) ORDER BY id",
                    tuple(ids),
                )
                rows = cur.fetchall()
            else:
                conditions = []
                params = []

                if filters.get("domain"):
                    conditions.append("domain LIKE %s")
                    params.append(f"%{filters['domain']}%")
                if filters.get("method"):
                    conditions.append("method = %s")
                    params.append(filters["method"].upper())
                if filters.get("graphql_only"):
                    conditions.append("is_graphql = 1")
                if filters.get("status_code") is not None:
                    conditions.append("status_code = %s")
                    params.append(filters["status_code"])

                where = ""
                if conditions:
                    where = "WHERE " + " AND ".join(conditions)

                limit = filters.get("limit", 200)
                cur.execute(
                    f"SELECT * FROM requests {where} ORDER BY id DESC LIMIT %s",
                    tuple(params + [limit]),
                )
                rows = cur.fetchall()

        return [self._row_to_dict(row) for row in rows]

    def delete_requests(self, pool, ids: Optional[list[int]] = None):
        with pool.cursor() as cur:
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
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
        # Ignore search_vector from the output
        if "search_vector" in d:
            del d["search_vector"]
        return d
