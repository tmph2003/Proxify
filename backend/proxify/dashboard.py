"""Web dashboard for viewing captured requests in real-time."""

import json
import logging
from pathlib import Path

from typing import Any
from aiohttp import web, WSMsgType

from proxify.exporter import (
    export_to_curl,
    export_to_har,
    export_to_json,
    export_to_python,
)
from proxify.core.traffic_storage import RequestStorage

logger = logging.getLogger("proxify.dashboard")


class Dashboard:
    """aiohttp-based web dashboard with WebSocket real-time updates."""

    def __init__(self, storage: RequestStorage, host: str = "0.0.0.0", port: int = 8888):
        self.storage = storage
        self.host = host
        self.port = port
        self.ws_clients: set[web.WebSocketResponse] = set()
        self.app = web.Application(client_max_size=50 * 1024 * 1024)
        self._setup_routes()

    def _setup_routes(self):
        # Serve API endpoints first
        self.app.router.add_get("/ws", self._handle_websocket)
        self.app.router.add_get("/api/requests", self._handle_list_requests)
        self.app.router.add_get("/api/requests/{id}", self._handle_get_request)
        self.app.router.add_get("/api/domains", self._handle_get_domains)
        self.app.router.add_get("/api/stats", self._handle_get_stats)
        self.app.router.add_get("/api/export/{format}", self._handle_export)
        self.app.router.add_delete("/api/requests", self._handle_delete_requests)
        self.app.router.add_post("/api/toggle_db", self._handle_toggle_db)
        self.app.router.add_get("/api/config", self._handle_get_config)
        # Server UI is now handled by Nginx completely.
        # We only keep the API endpoints here.
        # All SPA routing is now handled by Nginx.

    async def _handle_toggle_db(self, request: web.Request) -> web.Response:
        data = await request.json()
        if "enabled" in data:
            self.storage.db_integration_enabled = data["enabled"]
            logger.info(f"DB Integration {'ENABLED' if data['enabled'] else 'DISABLED'}")
        if "allowed_domains" in data:
            self.storage.db_allowed_domains = data["allowed_domains"]
            logger.info(f"DB Allowed Domains set to: {self.storage.db_allowed_domains}")
            
        return web.json_response({
            "status": "ok", 
            "db_integration_enabled": getattr(self.storage, 'db_integration_enabled', False),
            "db_allowed_domains": getattr(self.storage, 'db_allowed_domains', [])
        })

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        enabled = getattr(self.storage, 'db_integration_enabled', False)
        allowed_domains = getattr(self.storage, 'db_allowed_domains', [])
        return web.json_response({
            "db_integration_enabled": enabled,
            "db_allowed_domains": allowed_domains
        })

    async def broadcast(self, data: dict, msg_type: str = "new_request"):
        """Broadcast a message to all connected WebSocket clients."""
        msg = json.dumps({"type": msg_type, "data": data}, default=str)
        dead = set()
        for ws in self.ws_clients:
            try:
                await ws.send_str(msg)
            except (ConnectionError, RuntimeError):
                dead.add(ws)
        self.ws_clients -= dead

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections for real-time updates."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        logger.info(f"WebSocket client connected ({len(self.ws_clients)} total)")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Client can send filter preferences
                    pass
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self.ws_clients.discard(ws)
            logger.info(f"WebSocket client disconnected ({len(self.ws_clients)} total)")

        return ws

    def _get_start_of_today_epoch(self) -> float:
        from datetime import datetime
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    async def _handle_list_requests(self, request: web.Request) -> web.Response:
        """List captured requests with filters."""
        params = request.query
        try:
            results = self.storage.query_requests(
                domain=params.get("domain"),
                method=params.get("method"),
                status_code=int(params["status_code"]) if params.get("status_code") else None,
                search=params.get("search"),
                graphql_only=params.get("graphql_only") == "true",
                limit=int(params.get("limit", 200)),
                offset=int(params.get("offset", 0)),
                since=float(params["since"]) if params.get("since") else self._get_start_of_today_epoch(),
            )
        except (ValueError, TypeError) as e:
            return web.json_response({"error": f"Invalid parameter: {e}"}, status=400)
        return web.json_response(results, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_get_request(self, request: web.Request) -> web.Response:
        """Get a single request with full details."""
        try:
            request_id = int(request.match_info["id"])
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid request ID"}, status=400)
        result = self.storage.get_request(request_id)
        if result is None:
            return web.json_response({"error": "Not found"}, status=404)
        return web.json_response(result, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_get_domains(self, request: web.Request) -> web.Response:
        """Get unique domains with counts."""
        domains = self.storage.get_domains(since=self._get_start_of_today_epoch())
        return web.json_response(domains)

    async def _handle_get_stats(self, request: web.Request) -> web.Response:
        """Get capture statistics."""
        stats = self.storage.get_stats(since=self._get_start_of_today_epoch())
        return web.json_response(stats, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_export(self, request: web.Request) -> web.Response:
        """Export requests in various formats."""
        fmt = request.match_info["format"]
        params = request.query

        # Get IDs to export
        ids = None
        if params.get("ids"):
            ids = [int(x) for x in params["ids"].split(",")]

        filters: dict[str, Any] = {}
        if params.get("domain"):
            filters["domain"] = params["domain"]
        if params.get("method"):
            filters["method"] = params["method"]
        if params.get("graphql_only") == "true":
            filters["graphql_only"] = True

        requests_data = self.storage.get_requests_for_export(ids=ids, **filters)

        if fmt == "json":
            content = export_to_json(requests_data)
            return web.Response(
                text=content,
                content_type="application/json",
                headers={"Content-Disposition": "attachment; filename=requests.json"},
            )
        elif fmt == "har":
            content = export_to_har(requests_data)
            return web.Response(
                text=content,
                content_type="application/json",
                headers={"Content-Disposition": "attachment; filename=requests.har"},
            )
        elif fmt == "python":
            content = export_to_python(requests_data)
            return web.Response(
                text=content,
                content_type="text/plain",
                headers={"Content-Disposition": "attachment; filename=requests.py"},
            )
        elif fmt == "curl":
            content = export_to_curl(requests_data)
            return web.Response(
                text=content,
                content_type="text/plain",
                headers={"Content-Disposition": "attachment; filename=requests.sh"},
            )
        else:
            return web.json_response({"error": f"Unknown format: {fmt}"}, status=400)

    async def _handle_delete_requests(self, request: web.Request) -> web.Response:
        """Delete captured requests."""
        params = request.query
        ids = None
        if params.get("ids"):
            ids = [int(x) for x in params["ids"].split(",")]
        self.storage.delete_requests(ids)
        return web.json_response({"status": "ok"})

    async def _handle_stealth_verify(self, request: web.Request) -> web.Response:
        """Verify the current TLS fingerprint against a known test service."""
        from proxify.utils.stealth import StealthSessionManager

        manager = StealthSessionManager()
        try:
            fp_data = await manager.verify_fingerprint()
            if fp_data:
                return web.json_response({
                    "status": "ok",
                    "fingerprint": {
                        "ja3_hash": fp_data.get("ja3_hash", "N/A"),
                        "ja3_text": fp_data.get("ja3_text", "N/A"),
                        "protocol": fp_data.get("protocol", "N/A"),
                        "user_agent": fp_data.get("user_agent", "N/A"),
                        "tls_version": fp_data.get("tls_version", "N/A"),
                        "cipher_suite": fp_data.get("cipher_name", "N/A"),
                    },
                })
            return web.json_response(
                {"status": "error", "message": "Could not reach fingerprint service"},
                status=503,
            )
        except Exception as e:
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )
        finally:
            await manager.close()

    async def _handle_stealth_stats(self, request: web.Request) -> web.Response:
        """Return stealth engine statistics."""
        from proxify.platforms.facebook.crawler import _crawler_manager as crawler_mgr

        stats = {}
        if crawler_mgr:
            stats["crawler"] = crawler_mgr.stats
        else:
            stats["crawler"] = {"status": "not_initialized"}

        return web.json_response({"status": "ok", "data": stats})

    def get_app(self) -> web.Application:
        return self.app
