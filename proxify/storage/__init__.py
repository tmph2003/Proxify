import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from proxify.database import pool as shared_pool
from .repository import RequestRepository
from .workers import TTLWorker, AsyncWriterWorker

logger = logging.getLogger("proxify.storage")

_COMMIT_BATCH_SIZE = int(os.getenv("COMMIT_BATCH_SIZE", "50"))
DB_DSN = os.getenv("DB_DSN", "postgresql://proxify_user:proxify_pass@localhost:5432/proxify_db")


class RequestStorage:
    """Thread-safe PostgreSQL storage for HTTP request/response data."""

    def __init__(self, db_dsn: str = DB_DSN):
        self.db_dsn = db_dsn
        self.db_integration_enabled = os.getenv("DB_INTEGRATION_ENABLED", "false").lower() == "true"
        self.db_allowed_domains = []
        
        self._pool = shared_pool
        conn = self._pool.get_connection()
        if conn:
            self._db_available = True
            self._pool.release_connection(conn)
        else:
            self._db_available = False
            logger.warning(
                "⚠️  PostgreSQL not available. "
                "Proxy will run without DB storage. JS hooks still work."
            )
        
        self.repository = RequestRepository()
        
        if self._db_available:
            conn = self._pool.get_connection()
            try:
                self.repository.init_db(conn)
            finally:
                self._pool.release_connection(conn)
            
            # Initialize and start workers
            self.ttl_worker = TTLWorker(self._pool, self.repository)
            self.async_writer = AsyncWriterWorker(self._pool, self.repository, batch_size=_COMMIT_BATCH_SIZE)
            
            self.ttl_worker.start()
            self.async_writer.start()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _prepare_request_data(self, data: dict) -> tuple:
        now = datetime.now(timezone.utc)
        is_graphql = False
        graphql_operation = None
        graphql_doc_id = None
        graphql_variables = None

        request_body = data.get("request_body", "")
        url = data.get("url", "")

        from proxify.utils.graphql import parse_graphql_request
        if "graphql" in url.lower() or "graphql" in (data.get("path", "") or "").lower():
            is_graphql = True
            if request_body:
                operation, doc_id, vars_raw = parse_graphql_request(request_body)
                if operation:
                    graphql_operation = operation
                if doc_id:
                    graphql_doc_id = doc_id
                if vars_raw:
                    graphql_variables = vars_raw

        req_headers = data.get("request_headers", {})
        resp_headers = data.get("response_headers", {})
        if isinstance(req_headers, dict):
            req_headers = json.dumps(req_headers, ensure_ascii=False)
        if isinstance(resp_headers, dict):
            resp_headers = json.dumps(resp_headers, ensure_ascii=False)

        return (
            now.isoformat(),
            now.timestamp(),
            data.get("method", "GET"),
            url,
            data.get("scheme", "https"),
            data.get("domain", ""),
            data.get("port"),
            data.get("path", ""),
            data.get("query_string", ""),
            req_headers,
            request_body,
            data.get("request_content_type", ""),
            data.get("status_code"),
            resp_headers,
            data.get("response_body", ""),
            data.get("response_content_type", ""),
            data.get("response_size", 0),
            data.get("duration_ms"),
            int(is_graphql),
            graphql_operation,
            graphql_doc_id,
            graphql_variables,
        )

    def flush(self):
        """Block until all queued async writes are completed."""
        if self._db_available and hasattr(self, "async_writer"):
            self.async_writer.flush()

    def save_request(self, data: dict) -> int:
        if not self._db_available:
            return 0
        params = self._prepare_request_data(data)
        conn = self._pool.get_connection()
        try:
            return self.repository.save_request(conn, params)
        finally:
            self._pool.release_connection(conn)

    def save_request_async(self, data: dict, callback=None):
        """Queue a request to be saved asynchronously."""
        if not self._db_available:
            return
        params = self._prepare_request_data(data)
        self.async_writer.enqueue(params, callback)

    def get_request(self, request_id: int) -> Optional[dict]:
        """Get a single request by ID."""
        if not self._db_available:
            return None
        self.flush()
        return self.repository.get_request(self._pool, request_id)

    def query_requests(
        self,
        domain: Optional[str] = None,
        method: Optional[str] = None,
        status_code: Optional[int] = None,
        search: Optional[str] = None,
        graphql_only: bool = False,
        limit: int = 200,
        offset: int = 0,
        since: Optional[float] = None,
    ) -> list[dict]:
        """Query requests with filters."""
        if not self._db_available:
            return []
        self.flush()
        return self.repository.query_requests(
            self._pool, domain, method, status_code, search, graphql_only, limit, offset, since
        )

    def get_domains(self, since: Optional[float] = None) -> list[dict]:
        """Get all unique domains with request counts."""
        if not self._db_available:
            return []
        self.flush()
        return self.repository.get_domains(self._pool, since)

    def get_stats(self, since: Optional[float] = None) -> dict:
        """Get overall capture statistics."""
        if not self._db_available:
            return {}
        self.flush()
        return self.repository.get_stats(self._pool, since)

    def get_requests_for_export(
        self, ids: Optional[list[int]] = None, **filters
    ) -> list[dict]:
        """Get full request data for export."""
        if not self._db_available:
            return []
        self.flush()
        return self.repository.get_requests_for_export(self._pool, ids, **filters)

    def delete_requests(self, ids: Optional[list[int]] = None):
        """Delete requests by IDs, or all if ids is None."""
        if not self._db_available:
            return
        self.repository.delete_requests(self._pool, ids)

    def close(self):
        """Close the database connections."""
        if self._db_available:
            self.ttl_worker.stop()
            self.async_writer.stop()
            self.ttl_worker.join()
            self.async_writer.join()
        if hasattr(self, "_pool") and self._pool:
            self._pool = None
