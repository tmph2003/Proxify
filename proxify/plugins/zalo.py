"""Zalo Extractor Plugin."""

import json
import subprocess
import sys
import os
import signal
from pathlib import Path
from typing import Any, List, Dict, Optional
from aiohttp import web
from mitmproxy import http

from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin
from proxify.platforms.zalo.extractor import handle_capture_dump, modify_zalo_response
from proxify.platforms.zalo import zalo_db

@register_plugin("zalo")
class ZaloPlugin(BasePlugin):
    name = "Zalo Extractor"
    description = "Trích xuất dữ liệu tự động từ Zalo Web (Group, Members, Chat)"

    def __init__(self, storage=None, config=None):
        super().__init__(storage, config)
        self._bot_process: Optional[subprocess.Popen] = None
        self._pending_commands: list = []  # Commands for JS hooks to execute

    async def on_request(self, flow: Any) -> None:
        """Intercept decrypted payload dumps from Zalo JS hooks."""
        if not isinstance(flow, http.HTTPFlow):
            return
        # Fast skip: only process Zalo domains
        domain = flow.request.pretty_host
        if 'zalo' not in domain and 'zdn.vn' not in domain:
            return
        if "api/zalo/commands/pending" in flow.request.path:
            commands = list(self._pending_commands)
            self._pending_commands.clear()
            flow.response = http.Response.make(
                200,
                json.dumps(commands).encode("utf-8"),
                {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
            )
            return

        if handle_capture_dump(flow):
            pass

    async def on_response(self, flow: Any) -> None:
        """Inject Zalo JS hooks into responses."""
        if not isinstance(flow, http.HTTPFlow):
            return
        # Fast skip: only process Zalo domains
        domain = flow.request.pretty_host
        if 'zalo' not in domain and 'zdn.vn' not in domain:
            return
        modify_zalo_response(flow)
        
    def get_ui_tabs(self) -> List[Dict[str, str]]:
        """Return UI tabs for the dashboard."""
        return [
            {
                "id": "zalo-extractor",
                "label": "Zalo Extractor",
                "url": "/zalo"
            }
        ]

    def get_api_routes(self) -> List[web.RouteDef]:
        """Provide API routes for the Dashboard."""
        return [
            web.get("/zalo", self._handle_zalo_page),
            web.get("/api/zalo/stats", self._handle_zalo_stats),
            web.get("/api/zalo/groups", self._handle_zalo_groups),
            web.get("/api/zalo/groups/{group_id}/members", self._handle_zalo_group_members),
            web.get("/api/zalo/groups/{group_id}/export", self._handle_zalo_export),
            web.get("/api/zalo/users", self._handle_zalo_users),
            web.post("/api/zalo/scan", self._handle_zalo_scan),
            web.get("/api/zalo/jobs", self._handle_zalo_jobs),
            web.post("/api/zalo/jobs/{job_id}/cancel", self._handle_zalo_cancel_job),
            web.post("/api/zalo/bot/start", self._handle_bot_start),
            web.post("/api/zalo/bot/stop", self._handle_bot_stop),
            web.get("/api/zalo/bot/status", self._handle_bot_status),
            # Pending commands for JS hooks
            web.get("/api/zalo/commands/pending", self._handle_pending_commands),
            web.post("/api/zalo/commands/fetch_members", self._handle_fetch_members_command),
        ]

    # ── Zalo API Handlers ──

    async def _handle_zalo_page(self, request: web.Request) -> web.Response:
        """Serve the Zalo Extractor HTML page."""
        template_path = Path(__file__).parent.parent / "ui" / "templates" / "zalo.html"
        html = template_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def _handle_zalo_stats(self, request: web.Request) -> web.Response:
        """Get Zalo extraction statistics."""
        stats = zalo_db.get_stats()
        return web.json_response(stats)

    async def _handle_zalo_groups(self, request: web.Request) -> web.Response:
        """List Zalo groups."""
        params = request.query
        groups = zalo_db.groups.get_all(
            search=params.get("search"),
            limit=int(params.get("limit", 100)),
            offset=int(params.get("offset", 0)),
        )
        return web.json_response(groups, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_zalo_group_members(self, request: web.Request) -> web.Response:
        """List members of a Zalo group."""
        group_id = request.match_info["group_id"]
        params = request.query
        members = zalo_db.groups.get_members(
            group_id,
            search=params.get("search"),
            limit=int(params.get("limit", 500)),
            offset=int(params.get("offset", 0)),
        )
        return web.json_response(members, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_zalo_export(self, request: web.Request) -> web.Response:
        """Export group members as CSV or JSON."""
        group_id = request.match_info["group_id"]
        fmt = request.query.get("format", "csv")

        if fmt == "csv":
            csv_data = zalo_db.groups.export_members_csv(group_id)
            return web.Response(
                text=csv_data,
                content_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=zalo_group_{group_id}.csv"},
            )
        else:
            members = zalo_db.groups.get_members(group_id, limit=100000)
            return web.Response(
                text=json.dumps(members, ensure_ascii=False, indent=2, default=str),
                content_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=zalo_group_{group_id}.json"},
            )

    async def _handle_zalo_users(self, request: web.Request) -> web.Response:
        """List all Zalo users."""
        params = request.query
        users = zalo_db.users.get_all(
            search=params.get("search"),
            limit=int(params.get("limit", 200)),
            offset=int(params.get("offset", 0)),
        )
        return web.json_response(users, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_zalo_scan(self, request: web.Request) -> web.Response:
        """Submit a new Zalo group scan job."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

        link = data.get("link", "").strip()
        group_id = data.get("group_id", "").strip()

        if group_id:
            job_link = f"group_id:{group_id}"
        elif link:
            job_link = link
        else:
            return web.json_response({"status": "error", "error": "Link or group_id is required"}, status=400)

        job_id = zalo_db.jobs.create(job_link)
        if job_id is None:
            return web.json_response({"status": "error", "error": "Database error"}, status=500)

        return web.json_response({"status": "ok", "job_id": job_id})

    async def _handle_zalo_jobs(self, request: web.Request) -> web.Response:
        """List recent scan jobs."""
        jobs = zalo_db.jobs.get_all(limit=50)
        return web.json_response(jobs, dumps=lambda x: json.dumps(x, default=str))

    async def _handle_zalo_cancel_job(self, request: web.Request) -> web.Response:
        """Cancel a pending or running scan job."""
        try:
            job_id = int(request.match_info["job_id"])
            zalo_db.jobs.update(job_id, status="cancelled", completed_at="CURRENT_TIMESTAMP", error_message="User cancelled")
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    # ── Bot Management ──

    def _is_bot_alive(self) -> bool:
        """Check if the bot subprocess is alive."""
        return self._bot_process is not None and self._bot_process.poll() is None

    async def _handle_bot_start(self, request: web.Request) -> web.Response:
        """Start the Zalo bot subprocess."""
        if self._is_bot_alive():
            return web.json_response({"status": "ok", "message": "Bot đang chạy rồi", "running": True})

        try:
            env = os.environ.copy()
            # Ensure DB_DSN is passed to subprocess
            if "DB_DSN" not in env:
                env["DB_DSN"] = "postgresql://proxify_user:proxify_pass@localhost:5432/proxify_db"

            self._bot_process = subprocess.Popen(
                [sys.executable, "-m", "proxify.platforms.zalo.bot"],
                env=env,
                cwd=str(Path(__file__).parent.parent.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            )
            return web.json_response({"status": "ok", "message": "Bot đã khởi động", "pid": self._bot_process.pid, "running": True})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def _handle_bot_stop(self, request: web.Request) -> web.Response:
        """Stop the Zalo bot subprocess."""
        if not self._is_bot_alive():
            self._bot_process = None
            return web.json_response({"status": "ok", "message": "Bot không chạy", "running": False})

        try:
            if os.name == 'nt':
                self._bot_process.terminate()
            else:
                self._bot_process.send_signal(signal.SIGTERM)
            self._bot_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._bot_process.kill()
        except Exception:
            pass
        self._bot_process = None
        return web.json_response({"status": "ok", "message": "Bot đã dừng", "running": False})

    async def _handle_bot_status(self, request: web.Request) -> web.Response:
        """Check if the bot subprocess is running."""
        running = self._is_bot_alive()
        pid = self._bot_process.pid if running else None
        return web.json_response({"running": running, "pid": pid})

    # ── Pending Commands for JS Hooks ──

    async def _handle_pending_commands(self, request: web.Request) -> web.Response:
        """Return and clear pending commands for JS hooks.
        Called by JS hooks running in the user's browser (chat.zalo.me).
        """
        commands = list(self._pending_commands)
        self._pending_commands.clear()
        return web.json_response(commands)

    async def _handle_fetch_members_command(self, request: web.Request) -> web.Response:
        """Queue a fetch_members command for JS hooks to execute."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

        group_id = str(data.get("group_id", "")).strip()
        if not group_id:
            return web.json_response({"status": "error", "error": "group_id required"}, status=400)

        self._pending_commands.append({
            "action": "fetch_members",
            "group_id": group_id,
        })
        self.logger.info(f"[ZALO] Queued fetch_members command for group {group_id}")
        return web.json_response({"status": "ok", "message": f"Đã gửi lệnh lấy thành viên nhóm {group_id}. Chờ JS hooks xử lý..."})

    async def shutdown(self):
        """Clean up bot subprocess on shutdown."""
        if self._is_bot_alive():
            self._bot_process.terminate()
            try:
                self._bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._bot_process.kill()

