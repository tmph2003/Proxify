import logging
from typing import Callable, Any
from urllib.parse import urlparse
from mitmproxy import http
import time

logger = logging.getLogger("proxify.listeners")

from proxify.utils.content import is_text_content as _is_text_content, MAX_RESPONSE_SIZE

from proxify.core.interfaces import EventListener

class DashboardBroadcaster(EventListener):
    def __init__(self, broadcast_fn: Callable):
        self.broadcast_fn = broadcast_fn

    def __call__(self, flow: http.HTTPFlow, db_save: bool, **kwargs):
        """Format and broadcast summary metadata to the Dashboard."""
        if self.broadcast_fn is None:
            return

        request = flow.request
        response = flow.response
        if response is None:
            return

        parsed = urlparse(request.pretty_url)
        domain = parsed.hostname or ""
        path = parsed.path or ""

        start_time = getattr(request, "timestamp_start", None)
        duration_ms = None
        if start_time is not None:
            duration_ms = round((time.time() - start_time) * 1000, 2)

        resp_content_type = response.headers.get("content-type", "")
        resp_size = len(response.content) if response.content else 0

        is_graphql = "graphql" in path.lower()
        
        from datetime import datetime, timezone
        ts_iso = datetime.now(timezone.utc).isoformat()

        summary = {
            "id": 0,
            "req_uuid": flow.id,
            "method": request.method,
            "url": request.pretty_url,
            "domain": domain,
            "path": path,
            "status_code": response.status_code,
            "response_content_type": resp_content_type,
            "response_size": resp_size,
            "duration_ms": duration_ms,
            "is_graphql": int(is_graphql),
            "graphql_operation": None,
            "timestamp": ts_iso,
        }
        try:
            self.broadcast_fn(summary)
        except Exception:
            pass


class DatabaseWriter(EventListener):
    def __init__(self, storage):
        self.storage = storage

    def __call__(self, flow: http.HTTPFlow, db_save: bool, **kwargs):
        """Decode and queue full request data to the Database."""
        if not db_save:
            return

        request = flow.request
        response = flow.response
        if response is None:
            return

        parsed = urlparse(request.pretty_url)
        domain = parsed.hostname or ""
        port = parsed.port
        path = parsed.path or ""

        start_time = getattr(request, "timestamp_start", None)
        duration_ms = None
        if start_time is not None:
            duration_ms = round((time.time() - start_time) * 1000, 2)

        resp_content_type = response.headers.get("content-type", "")
        resp_size = len(response.content) if response.content else 0

        req_headers = {k: ("[REDACTED]" if k.lower() == "cookie" else v) for k, v in request.headers.items()}
        req_content_type = request.headers.get("content-type", "")
        req_body = None
        
        if request.content:
            try:
                req_body = request.text
            except ValueError:
                req_body = f"[Binary data: {len(request.content)} bytes]"

        resp_headers = {k: ("[REDACTED]" if k.lower() == "set-cookie" else v) for k, v in response.headers.items()}
        resp_body = None
        if response.content and resp_size <= MAX_RESPONSE_SIZE:
            if _is_text_content(resp_content_type):
                try:
                    resp_body = response.text
                except ValueError:
                    resp_body = f"[Decode error: {resp_size} bytes]"
            else:
                resp_body = f"[Binary: {resp_content_type}, {resp_size} bytes]"
        elif resp_size > MAX_RESPONSE_SIZE:
            resp_body = f"[Too large: {resp_size} bytes, max {MAX_RESPONSE_SIZE}]"

        if isinstance(req_body, str):
            req_body = req_body.replace('\x00', '')
        if isinstance(resp_body, str):
            resp_body = resp_body.replace('\x00', '')

        data = {
            "method": request.method,
            "url": request.pretty_url,
            "scheme": parsed.scheme,
            "domain": domain,
            "port": port,
            "path": path,
            "query_string": parsed.query,
            "request_headers": req_headers,
            "request_body": req_body,
            "request_content_type": req_content_type,
            "status_code": response.status_code,
            "response_headers": resp_headers,
            "response_body": resp_body,
            "response_content_type": resp_content_type,
            "response_size": resp_size,
            "duration_ms": duration_ms,
        }

        is_graphql = "graphql" in path.lower()
        gql_tag = " [GraphQL]" if is_graphql else ""

        def _on_saved(row_id: int):
            logger.info(
                f"#{row_id} {request.method} {response.status_code} "
                f"{domain}{path}{gql_tag} ({duration_ms}ms, {resp_size}B)"
            )
            from proxify.core.events import bus
            bus.publish("db_row_created", req_uuid=flow.id, row_id=row_id)
            
        self.storage.save_request_async(data, callback=_on_saved)

