"""Facebook Extractor Plugin."""

import json
import uuid
from pathlib import Path
from typing import Any, List, Dict
from aiohttp import web
from mitmproxy import http
import logging

from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin

background_tasks = set()

# Multi-Tenant In-Memory Cookie & Identity Store (Imported from auth.py)
from proxify.platforms.facebook.auth import (
    TENANT_COOKIES,
    IN_MEMORY_COOKIES,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
)

logger = logging.getLogger("proxify.facebook")

class FacebookAPI:
    """Facebook API Routes for Dashboard"""
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._cached_groups = None
        self._cached_groups_time = 0
        self._bulk_progress = {}

    def get_api_routes(self) -> List[web.RouteDef]:
        return [
            web.get("/facebook", self._handle_facebook_page),
            web.post("/api/facebook/crawl", self._handle_facebook_crawl),
            web.get("/api/facebook/results", self._handle_facebook_results),
            web.get("/api/facebook/groups", self._handle_get_groups),
            web.post("/api/facebook/crawl_posts", self._handle_crawl_posts),
            web.get("/api/facebook/crawl_status", self._handle_crawl_status),
            web.post("/api/facebook/cookie", self._handle_save_cookie),
            web.get("/api/facebook/cookie", self._handle_get_cookie),
            web.get("/api/facebook/comments", self._handle_get_comments),
            web.post("/api/facebook/crawl_comments", self._handle_crawl_comments),
            web.get("/api/facebook/comment_status", self._handle_comment_status),
            web.post("/api/facebook/bulk_action", self._handle_bulk_action),
            web.patch("/api/facebook/post_status", self._handle_post_status),
            web.get("/api/facebook/bulk_status", self._handle_bulk_status),
            web.post("/api/facebook/stop_crawl", self._handle_stop_crawl),
            web.post("/api/facebook/stop_comment_crawl", self._handle_stop_comment_crawl),
            
            # Bridge Endpoints
            web.get("/api/facebook/bridge/jobs", self._handle_bridge_jobs),
            web.post("/api/facebook/bridge/result", self._handle_bridge_result),
        ]

    async def _handle_bridge_jobs(self, request: web.Request) -> web.Response:
        """Extension polls this endpoint for jobs (Short-Polling), segregated by client_id."""
        import time
        from proxify.platforms.facebook.bridge import bridge
        
        client_id = request.query.get("client_id") or request.headers.get("X-Client-ID") or "default"
        bridge.client_last_poll[client_id] = time.time()
        job = bridge.get_job(client_id=client_id)
        if job:
            return web.json_response({"job": job})
            
        return web.json_response({"job": None})
        
    async def _handle_bridge_result(self, request: web.Request) -> web.Response:
        """Extension submits job result here."""
        from proxify.platforms.facebook.bridge import bridge
        
        try:
            data = await request.json()
            job_id = data.get("id")
            result = data.get("result")
            client_id = data.get("client_id") or request.headers.get("X-Client-ID") or "default"
            if job_id and result:
                bridge.complete_job(job_id, result, client_id=client_id)
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"[Bridge] Error handling result: {e}")
            return web.json_response({"status": "error"}, status=400)

    async def _handle_stop_crawl(self, request: web.Request) -> web.Response:
        try:
            from proxify.platforms.facebook.crawler import _default_crawler
            _default_crawler.stop_crawling()
            return web.json_response({"status": "ok", "message": "Đã gửi lệnh dừng thu thập dữ liệu."})
        except Exception as e:
            logger.error(f"Error stopping crawl: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_stop_comment_crawl(self, request: web.Request) -> web.Response:
        try:
            body = await request.json() if request.can_read_body else {}
            post_id = body.get("post_id")
            from proxify.platforms.facebook.crawler import _default_crawler
            _default_crawler.stop_comment_crawling(post_id)
            return web.json_response({"status": "ok", "message": "Đã gửi lệnh dừng cào bình luận."})
        except Exception as e:
            logger.error(f"Error stopping comment crawl: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_get_groups(self, request: web.Request) -> web.Response:
        import time
        now = time.time()
        if self._cached_groups and (now - self._cached_groups_time) < 300:
            return web.json_response({"status": "ok", "data": self._cached_groups})
            
        try:
            if not self.db_pool:
                raise Exception("Database pool not initialized")
                
            async with self.db_pool.acquire() as conn:
                groups = await conn.fetch("""
                    SELECT 
                        MAX(
                            COALESCE(
                                NULLIF(trim(group_id), ''), 
                                substring(permalink_url from '/groups/([^/]+)/')
                            )
                        ) as group_id, 
                        trim(group_name) as group_name
                    FROM facebook.posts
                    WHERE group_name IS NOT NULL AND trim(group_name) != ''
                    GROUP BY trim(group_name)
                """)
                
                # Convert asyncpg.Record to dict
                groups = [dict(g) for g in groups]
                groups.sort(key=lambda x: (x.get('group_name') or '').lower())
                
                self._cached_groups = groups
                self._cached_groups_time = now
                
            return web.json_response({
                "status": "ok",
                "data": groups
            })
        except Exception as e:
            logger.error(f"Error fetching groups: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_facebook_page(self, request: web.Request) -> web.Response:
        template_path = Path(__file__).parent.parent.parent / "ui" / "templates" / "facebook.html"
        if not template_path.exists():
            return web.Response(text="Template not found", status=404)
        html = template_path.read_text(encoding="utf-8")
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        return web.Response(text=html, content_type="text/html", headers=headers)
        
    async def _handle_facebook_crawl(self, request: web.Request) -> web.Response:
        data = await request.json()
        # Support both old "group_id" and new "target_id" + "target_type"
        target_type = data.get("target_type", "group")
        target_id = data.get("target_id") or data.get("group_id")
        group_id = target_id  # backward compat alias
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")
        cookie = data.get("cookie", "")
        fb_dtsg_input = data.get("fb_dtsg", "").strip()
        client_id = data.get("client_id") or request.headers.get("X-Client-ID") or "default"
        
        if not target_id:
            label = "Group ID" if target_type == "group" else "Profile ID"
            return web.json_response({"status": "error", "message": f"Missing {label}"}, status=400)
            

        import asyncio
        from datetime import datetime, timezone
        from proxify.platforms.facebook.crawler import start_crawler, group_crawl_state, is_any_comment_crawling

        # Mutually exclusive crawling: block post crawl if comment crawl is running
        if is_any_comment_crawling():
            return web.json_response({
                "status": "error",
                "message": "⚠️ Đang có tiến trình cào bình luận (Comment) đang chạy. Vui lòng chờ hoàn tất trước khi cào bài viết."
            }, status=400)
        
        try:
            # Parse dates and convert to UTC timestamps
            start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) if start_date_str else 0
            # Inclusive end date (+24h)
            end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 86400 if end_date_str else 0
            
            if start_ts and end_ts and start_ts > end_ts:
                return web.json_response({"status": "error", "message": "start_date cannot be greater than end_date"}, status=400)
                
        except Exception as e:
            return web.json_response({"status": "error", "message": f"Invalid date format: {e}"}, status=400)
            
        from proxify.platforms.facebook.auth import IN_MEMORY_TEMPLATES
        tenant_cookie = TENANT_COOKIES.get(client_id, {})
        
        # Extract User-Agent from the incoming request (crucial for Facebook fingerprinting)
        client_ua = request.headers.get("User-Agent", tenant_cookie.get("user_agent") or IN_MEMORY_COOKIES.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        
        # Fallback to in-memory cookie if UI didn't send one
        if not cookie:
            cookie = tenant_cookie.get("cookie", "") or IN_MEMORY_COOKIES.get("cookie", "")

        async def _crawl_with_fresh_template():
            """Fetch fresh template via Playwright in a subprocess, then start crawler."""
            try:
                import subprocess
                import sys
                import json
                import os
                import asyncio
                from pathlib import Path
                from proxify.platforms.facebook.crawler import start_crawler, group_crawl_state

                group_crawl_state["status"] = "fetching_template"
                group_crawl_state["group_id"] = group_id
                group_crawl_state["message"] = (
                    f"🔄 Đang lấy token mới từ Facebook cho Group {group_id}...\n"
                    "Playwright đang mở trang group để bắt request GraphQL."
                )

                cookie_str = cookie or tenant_cookie.get("cookie", "") or IN_MEMORY_COOKIES.get("cookie", "")
                
                # INJECT FRESH auth headers from Extension if available
                # This fixes Facebook Error 1357001 caused by fb_dtsg mismatch when cookie is pasted/updated via UI
                from proxify.platforms.facebook.auth import IN_MEMORY_TEMPLATES
                fb_dtsg = tenant_cookie.get("fb_dtsg") or IN_MEMORY_COOKIES.get("fb_dtsg")
                lsd = tenant_cookie.get("lsd") or IN_MEMORY_COOKIES.get("lsd")
                
                # Fallback to persistent DB if server was restarted
                if not fb_dtsg:
                    try:
                        from proxify.platforms.facebook.database import fb_db
                        fb_dtsg = fb_db.config.get("fb_dtsg")
                        lsd = lsd or fb_db.config.get("lsd")
                        if fb_dtsg:
                            tenant_cookie["fb_dtsg"] = fb_dtsg
                            IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg
                        if lsd:
                            tenant_cookie["lsd"] = lsd
                            IN_MEMORY_COOKIES["lsd"] = lsd
                    except Exception:
                        pass

                if not fb_dtsg:
                    try:
                        from proxify.database import pool as shared_pool
                        import urllib.parse
                        with shared_pool.cursor() as cur:
                            cur.execute("SELECT request_body FROM requests WHERE request_body LIKE '%fb_dtsg=%' ORDER BY id DESC LIMIT 1")
                            row = cur.fetchone()
                            if row:
                                parsed = urllib.parse.parse_qs(row[0])
                                if parsed.get("fb_dtsg"):
                                    fb_dtsg = parsed["fb_dtsg"][0]
                                    tenant_cookie["fb_dtsg"] = fb_dtsg
                                    IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg
                                if parsed.get("lsd") and not lsd:
                                    lsd = parsed["lsd"][0]
                                    tenant_cookie["lsd"] = lsd
                                    IN_MEMORY_COOKIES["lsd"] = lsd
                    except Exception as e:
                        logger.debug(f"[Crawler Start] Error fetching fb_dtsg from requests: {e}")

                logger.info(f"[Crawler Start] TENANT_COOKIES keys for '{client_id}': {list(tenant_cookie.keys())}")
                
                # If the user provided fb_dtsg manually via the UI, use it and avoid fetching!
                if fb_dtsg_input:
                    fb_dtsg = fb_dtsg_input
                    tenant_cookie["fb_dtsg"] = fb_dtsg_input
                    IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg_input
                
                # Ensure fb_dtsg is present to avoid Facebook bot logout
                if not fb_dtsg and not fb_dtsg_input:
                    group_crawl_state["status"] = "error"
                    group_crawl_state["message"] = (
                        "⚠️ Chưa nhận được mã bảo mật fb_dtsg từ Extension.\n\n"
                        "👉 Hướng dẫn an toàn (tránh bị Facebook logout):\n"
                        "1. Mở sẵn 1 tab Facebook (facebook.com) trên trình duyệt.\n"
                        "2. Mở Extension Proxify và bấm 'Bắn Cookie vào Proxify'.\n"
                        "3. Sau khi Extension báo 'ĐỒNG BỘ THÀNH CÔNG', quay lại đây bấm 'Bắt đầu thu thập'!"
                    )
                    return

                if fb_dtsg and lsd:
                    for key in ["feed", "comment", "reply"]:
                        if key in IN_MEMORY_TEMPLATES and isinstance(IN_MEMORY_TEMPLATES[key], dict) and "form_data" in IN_MEMORY_TEMPLATES[key]:
                            IN_MEMORY_TEMPLATES[key]["form_data"]["fb_dtsg"] = fb_dtsg
                            IN_MEMORY_TEMPLATES[key]["form_data"]["lsd"] = lsd
                            
                try:
                    if target_type == "profile":
                        from proxify.platforms.facebook.crawler import start_profile_crawler
                        await start_profile_crawler(target_id, start_ts, end_ts, client_cookie=cookie_str, client_id=client_id)
                    else:
                        await start_crawler(group_id, start_ts, end_ts, client_cookie=cookie_str, client_id=client_id)
                except Exception as e:
                    import traceback
                    logger.error(f"FATAL error in start_crawler: {e}")
                    logger.error(traceback.format_exc())
                    group_crawl_state["status"] = "error"
                    group_crawl_state["message"] = f"Lỗi nội bộ: {e}"
                        
                except Exception as e:
                    logger.error(f"Error running lightweight template fetcher: {e}")
                    group_crawl_state["status"] = "error"
                    group_crawl_state["message"] = f"Lỗi nội bộ khi khởi tạo: {e}"
            finally:
                pass
                
        # Run Playwright template fetcher in background
        task = asyncio.create_task(_crawl_with_fresh_template())
        
        # Keep a strong reference to avoid garbage collection
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        return web.json_response({"status": "ok", "message": "Crawler started"})

    async def _handle_crawl_posts(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            urls = body.get("urls", [])
            if not urls:
                return web.json_response({"status": "error", "message": "No URLs provided"}, status=400)
            
            from proxify.platforms.facebook.crawler import crawl_specific_posts, refresh_progress
            import asyncio
            
            # Set status synchronously so frontend polling doesn't immediately stop
            refresh_progress["total"] = len(urls)
            refresh_progress["current"] = 0
            refresh_progress["status"] = "running"
            
            # Start background task to visit these URLs
            asyncio.create_task(crawl_specific_posts(urls))
            return web.json_response({"status": "ok", "message": f"Started crawling {len(urls)} posts"})
            
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_crawl_status(self, request: web.Request) -> web.Response:
        from proxify.platforms.facebook.crawler import refresh_progress, group_crawl_state, is_any_comment_crawling, is_post_crawling
        return web.json_response({
            "refresh": refresh_progress,
            "group_crawl": group_crawl_state,
            "is_comment_crawling": is_any_comment_crawling(),
            "is_post_crawling": is_post_crawling(),
        })

    async def _handle_facebook_results(self, request: web.Request) -> web.Response:
        sort_by = request.query.get("sort", "time")
        order = request.query.get("order", "DESC").upper()
        if order not in ["ASC", "DESC"]:
            order = "DESC"
            
        group_id = request.query.get("group_id", "")
        group_name = request.query.get("group_name", "")
        status_filter = request.query.get("status", "")
        start_date = request.query.get("start_date", "")
        end_date = request.query.get("end_date", "")
            
        try:
            page = int(request.query.get("page", "1"))
        except ValueError:
            page = 1
            
        try:
            limit = int(request.query.get("limit", "10"))
        except ValueError:
            limit = 10
            
        offset = (page - 1) * limit

        if sort_by == "reaction":
            order_clause = f"ORDER BY p.reaction_count {order} NULLS LAST"
        elif sort_by == "comment":
            order_clause = f"ORDER BY p.comment_count {order} NULLS LAST"
        elif sort_by == "author":
            order_clause = f"ORDER BY p.author_name {order} NULLS LAST"
        elif sort_by == "content":
            order_clause = f"ORDER BY p.message_text {order} NULLS LAST"
        elif sort_by == "updated":
            order_clause = f"ORDER BY p.updated_at {order} NULLS LAST"
        else:
            order_clause = f"ORDER BY p.creation_time {order} NULLS LAST"
            
        try:
            if not self.db_pool:
                raise Exception("Database pool not initialized")
                
            async with self.db_pool.acquire() as conn:
                conditions = []
                params = []
                
                if group_id and group_name:
                    conditions.append(f"(p.group_id = ${len(params)+1} OR p.group_name = ${len(params)+2})")
                    params.extend([group_id, group_name])
                elif group_id:
                    conditions.append(f"p.group_id = ${len(params)+1}")
                    params.append(group_id)
                elif group_name:
                    conditions.append(f"p.group_name = ${len(params)+1}")
                    params.append(group_name)
                    
                if status_filter == "active":
                    conditions.append("p.is_active = TRUE")
                elif status_filter == "inactive":
                    conditions.append("p.is_active = FALSE")
                elif status_filter == "unknown":
                    conditions.append("p.is_active IS NULL")
                
                if start_date:
                    try:
                        from datetime import datetime, timezone
                        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                        conditions.append(f"p.creation_time >= ${len(params)+1}")
                        params.append(start_ts)
                    except ValueError:
                        pass
                        
                if end_date:
                    try:
                        from datetime import datetime, timezone
                        # Bao gồm cả ngày cuối cùng (+86400 giây)
                        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 86400
                        conditions.append(f"p.creation_time <= ${len(params)+1}")
                        params.append(end_ts)
                    except ValueError:
                        pass
                
                where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                    
                total = await conn.fetchval(f"SELECT COUNT(*) FROM facebook.posts p {where_clause}", *params)
                
                query_posts = f"""
                    SELECT p.post_id, p.author_name, a.profile_url, a.avatar_url,
                           p.creation_datetime, p.message_text,
                           p.permalink_url, p.reaction_count, p.comment_count,
                           p.feedback_id, p.is_active,
                           p.created_at + INTERVAL '7 hours' as created_at, 
                           p.updated_at + INTERVAL '7 hours' as updated_at,
                           (SELECT COUNT(*) FROM facebook.comments c2 WHERE c2.post_id = p.post_id) as crawled_comment_count
                    FROM facebook.posts p
                    LEFT JOIN facebook.authors a ON p.author_id = a.id
                    {where_clause}
                    {order_clause}
                    LIMIT ${len(params)+1} OFFSET ${len(params)+2}
                """
                
                posts_records = await conn.fetch(query_posts, *(params + [limit, offset]))
                posts = [dict(p) for p in posts_records]
                
                for p in posts:
                    if p["creation_datetime"] and hasattr(p["creation_datetime"], "isoformat"):
                        p["creation_datetime"] = p["creation_datetime"].isoformat()
                    if p.get("created_at") and hasattr(p["created_at"], "isoformat"):
                        p["created_at"] = p["created_at"].isoformat()
                    if p.get("updated_at") and hasattr(p["updated_at"], "isoformat"):
                        p["updated_at"] = p["updated_at"].isoformat()
                            
                return web.json_response({
                    "status": "ok", 
                    "data": posts,
                    "total": total,
                    "page": page,
                    "limit": limit
                })
        except Exception as e:
            logger.error(f"Error fetching results: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_get_comments(self, request: web.Request) -> web.Response:
        """Get comments for a specific post."""
        post_id = request.query.get("post_id", "")
        if not post_id:
            return web.json_response(
                {"status": "error", "message": "post_id is required"}, status=400
            )

        try:
            if not self.db_pool:
                raise Exception("Database pool not initialized")
                
            async with self.db_pool.acquire() as conn:
                comments_records = await conn.fetch("""
                    SELECT c.comment_id, c.post_id, c.parent_comment_id,
                           c.author_id, c.author_name, c.body_text,
                           c.body_text AS message_text,
                           c.creation_time, c.creation_datetime,
                           c.reaction_count, c.reply_count,
                           a.avatar_url,
                           a.avatar_url AS author_avatar
                    FROM facebook.comments c
                    LEFT JOIN facebook.authors a ON c.author_id = a.id
                    WHERE c.post_id = $1
                    ORDER BY c.creation_time ASC NULLS LAST
                """, post_id)
                
                comments = [dict(c) for c in comments_records]

                for c in comments:
                    if c.get("creation_datetime") and hasattr(c["creation_datetime"], "isoformat"):
                        c["creation_datetime"] = c["creation_datetime"].isoformat()

                return web.json_response({
                    "status": "ok",
                    "data": comments,
                    "total": len(comments),
                })
        except Exception as e:
            logger.error(f"Error fetching comments: {e}")
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )

    async def _handle_crawl_comments(self, request: web.Request) -> web.Response:
        """Start crawling comments for a specific post."""
        import asyncio
        try:
            body = await request.json()
            post_id = body.get("post_id", "")
            feedback_id = body.get("feedback_id", "")
            cookie = body.get("cookie", "")
            fb_dtsg = body.get("fb_dtsg", "")
            client_id = body.get("client_id") or request.headers.get("X-Client-ID") or "default"
            if fb_dtsg:
                TENANT_COOKIES.setdefault(client_id, {})["fb_dtsg"] = fb_dtsg
                IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg
            
            logger.info(f">>> UI CRAWL REQUEST RECEIVED! post_id: {post_id}, feedback_id: {feedback_id}, client_id: {client_id}")
            
            if not post_id:
                return web.json_response(
                    {"status": "error", "message": "post_id is required"}, status=400
                )

            from proxify.platforms.facebook.crawler import is_post_crawling
            # Mutually exclusive crawling: block comment crawl if post crawl is running
            if is_post_crawling():
                return web.json_response({
                    "status": "error",
                    "message": "⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Vui lòng chờ hoàn tất trước khi cào bình luận."
                }, status=400)
            
            # If no feedback_id provided, look it up from the database
            if not feedback_id:
                try:
                    from proxify.platforms.facebook.database import fb_db
                    with fb_db.pool.cursor(dict_cursor=True) as cur:
                        cur.execute(
                            "SELECT feedback_id FROM facebook.posts WHERE post_id = %s",
                            (post_id,),
                        )
                        row = cur.fetchone()
                        if row and row["feedback_id"]:
                            feedback_id = row["feedback_id"]
                            logger.info(f"Retrieved feedback_id {feedback_id} from DB for post {post_id}")
                except Exception as e:
                    logger.warning(f"Failed to look up feedback_id from DB: {e}")

            if not feedback_id:
                import base64
                feedback_id = base64.b64encode(f"feedback:{post_id}".encode()).decode()
                logger.info(f"Synthesized feedback_id {feedback_id} for post {post_id}")

            cookie = cookie or TENANT_COOKIES.get(client_id, {}).get("cookie", "")
            
            from proxify.platforms.facebook.crawler import crawl_post_comments
            
            # Run in background
            async def _bg_crawl():
                try:
                    await crawl_post_comments(post_id, feedback_id, client_cookie=cookie, client_id=client_id)
                except Exception as e:
                    import traceback
                    logger.error(f"Error in bg_crawl for {post_id}: {e}\n{traceback.format_exc()}")
            
            task = asyncio.create_task(_bg_crawl())
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
            
            return web.json_response({
                "status": "ok",
                "message": f"Comment crawl started for {post_id}"
            })
        except Exception as e:
            logger.error(f"Error starting comment crawl: {e}")
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )

    async def _handle_comment_status(self, request: web.Request) -> web.Response:
        """Get the current progress of a comment crawl."""
        post_id = request.query.get("post_id")
        if not post_id:
            return web.json_response({"status": "error", "message": "post_id required"})
        
        from proxify.platforms.facebook.crawler import get_comment_progress
        progress = get_comment_progress(post_id)
        
        logger.debug(f">>> UI STATUS POLL RECEIVED! post_id: {post_id}, progress_found: {progress is not None}")
        
        if progress:
            return web.json_response({"status": "ok", "progress": progress})
        return web.json_response({
            "status": "ok",
            "progress": {"status": "idle", "total": 0, "message": ""}
        })

    # ── Bulk Actions ─────────────────────────────────────────────

    _bulk_progress = {}  # task_id -> {status, current, total, message}

    async def _handle_post_status(self, request: web.Request) -> web.Response:
        """Update is_active status for one or more posts."""
        try:
            body = await request.json()
            post_ids = body.get("post_ids", [])
            is_active = body.get("is_active")  # True, False, or None
            
            if not post_ids:
                return web.json_response({"status": "error", "message": "post_ids required"}, status=400)
            
            if not self.db_pool:
                raise Exception("Database pool not initialized")
                
            async with self.db_pool.acquire() as conn:
                if is_active is None:
                    await conn.execute("UPDATE facebook.posts SET is_active = NULL WHERE post_id = ANY($1::text[])", post_ids)
                else:
                    await conn.execute("UPDATE facebook.posts SET is_active = $1 WHERE post_id = ANY($2::text[])", is_active, post_ids)
            
            return web.json_response({"status": "ok", "updated": len(post_ids)})
        except Exception as e:
            logger.error(f"Error updating post status: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_bulk_action(self, request: web.Request) -> web.Response:
        """Execute a bulk action on selected posts."""
        import asyncio
        from proxify.platforms.facebook.database import fb_db
        
        try:
            body = await request.json()
            action = body.get("action", "")
            post_ids = body.get("post_ids", [])
            cookie = body.get("cookie", "")
            client_id = body.get("client_id") or request.headers.get("X-Client-ID") or "default"
            
            if not post_ids:
                return web.json_response({"status": "error", "message": "post_ids required"}, status=400)
            
            task_id = f"bulk_{action}_{id(post_ids)}"
            
            if action == "crawl_comments":
                from proxify.platforms.facebook.crawler import is_post_crawling
                if is_post_crawling():
                    return web.json_response({
                        "status": "error",
                        "message": "⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Vui lòng chờ hoàn tất trước khi cào bình luận hàng loạt."
                    }, status=400)

                self._bulk_progress[task_id] = {"status": "running", "current": 0, "total": len(post_ids), "message": "Đang khởi tạo..."}
                
                async def _bg_bulk_crawl():
                    from proxify.platforms.facebook.crawler import crawl_post_comments
                    for i, pid in enumerate(post_ids):
                        self._bulk_progress[task_id] = {
                            "status": "running", "current": i + 1, "total": len(post_ids),
                            "message": f"Đang cào bình luận bài {i+1}/{len(post_ids)}..."
                        }
                        # Get feedback_id from DB
                        fb_id = ""
                        try:
                            with fb_db.pool.cursor(dict_cursor=True) as cur:
                                cur.execute("SELECT feedback_id FROM facebook.posts WHERE post_id = %s", (pid,))
                                row = cur.fetchone()
                                if row and row["feedback_id"]:
                                    fb_id = row["feedback_id"]
                        except Exception:
                            pass
                        
                        if not fb_id:
                            import base64
                            fb_id = base64.b64encode(f"feedback:{pid}".encode()).decode()
                        
                        try:
                            await crawl_post_comments(pid, fb_id, client_cookie=cookie)
                            # Wait until this post finishes or timeout 60s
                            from proxify.platforms.facebook.crawler import get_comment_progress
                            for _ in range(60):
                                prog = get_comment_progress(pid)
                                if prog and prog.get("status") in ["done", "error"]:
                                    break
                                await asyncio.sleep(1)
                        except Exception as e:
                            logger.error(f"Bulk crawl error for {pid}: {e}")
                        await asyncio.sleep(2)  # Rate limit between posts
                    
                    self._bulk_progress[task_id] = {
                        "status": "done", "current": len(post_ids), "total": len(post_ids),
                        "message": f"Hoàn tất cào bình luận {len(post_ids)} bài!"
                    }
                
                task = asyncio.create_task(_bg_bulk_crawl())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.json_response({"status": "ok", "task_id": task_id})
            
            elif action == "check_status":
                task_id = str(uuid.uuid4())[:8]
                self._bulk_progress[task_id] = {
                    "status": "running", "current": 0, "total": len(post_ids),
                    "message": f"Bắt đầu kiểm tra {len(post_ids)} bài..."
                }
                
                async def _bg_check_status():
                    from proxify.platforms.facebook.crawler import _default_crawler
                    crawler = _default_crawler
                    crawler.client_id = client_id
                    
                    for i, pid in enumerate(post_ids):
                        self._bulk_progress[task_id] = {
                            "status": "running", "current": i + 1, "total": len(post_ids),
                            "message": f"Đang kiểm tra bài {i+1}/{len(post_ids)}..."
                        }
                        
                        try:
                            await crawler.refresh_single_post(
                                post_id=pid,
                                client_cookie=cookie,
                                client_id=client_id
                            )
                        except Exception as e:
                            logger.error(f"Status check error for {pid}: {e}")
                        
                        if i + 1 < len(post_ids):
                            await asyncio.sleep(1.5)
                    
                    self._bulk_progress[task_id] = {
                        "status": "done", "current": len(post_ids), "total": len(post_ids),
                        "message": f"Đã kiểm tra {len(post_ids)} bài!"
                    }
                
                task = asyncio.create_task(_bg_check_status())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.json_response({"status": "ok", "task_id": task_id})
            
            elif action == "refresh":
                task_id = str(uuid.uuid4())[:8]
                self._bulk_progress[task_id] = {
                    "status": "running", "current": 0, "total": len(post_ids),
                    "message": f"Bắt đầu làm mới {len(post_ids)} bài viết..."
                }
                
                from proxify.platforms.facebook.crawler import refresh_progress, _default_crawler
                refresh_progress["total"] = len(post_ids)
                refresh_progress["current"] = 0
                refresh_progress["status"] = "running"
                
                async def _bg_refresh():
                    crawler = _default_crawler
                    crawler.client_id = client_id
                    updated_count = 0
                    
                    for i, pid in enumerate(post_ids):
                        self._bulk_progress[task_id] = {
                            "status": "running", "current": i + 1, "total": len(post_ids),
                            "message": f"Đang làm mới {i+1}/{len(post_ids)} bài viết..."
                        }
                        refresh_progress["current"] = i + 1
                        
                        try:
                            res = await crawler.refresh_single_post(
                                post_id=pid,
                                client_cookie=cookie,
                                client_id=client_id
                            )
                            if res.get("updated"):
                                updated_count += 1
                        except Exception as e:
                            logger.error(f"[Refresh] Lỗi khi làm mới bài {pid}: {e}")
                        
                        if i + 1 < len(post_ids):
                            await asyncio.sleep(1.5)
                            
                    self._bulk_progress[task_id] = {
                        "status": "done", "current": len(post_ids), "total": len(post_ids),
                        "message": f"Hoàn tất làm mới {len(post_ids)} bài viết ({updated_count} thành công)!"
                    }
                    refresh_progress["status"] = "idle"
                
                task = asyncio.create_task(_bg_refresh())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.json_response({"status": "ok", "task_id": task_id, "message": "Refresh started"})

            elif action == "export_csv":
                import csv
                import io
                
                with fb_db.pool.cursor(dict_cursor=True) as cur:
                    placeholders = ",".join(["%s"] * len(post_ids))
                    cur.execute(f"""
                        SELECT p.post_id, p.author_name, p.creation_datetime, 
                               p.message_text, p.permalink_url, p.reaction_count, 
                               p.comment_count, p.is_active,
                               (SELECT COUNT(*) FROM facebook.comments c WHERE c.post_id = p.post_id) as crawled_comments
                        FROM facebook.posts p
                        WHERE p.post_id IN ({placeholders})
                        ORDER BY p.creation_time DESC NULLS LAST
                    """, tuple(post_ids))
                    rows = cur.fetchall()
                
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=[
                    "post_id", "author_name", "creation_datetime", "message_text",
                    "permalink_url", "reaction_count", "comment_count", "crawled_comments", "is_active"
                ])
                writer.writeheader()
                for row in rows:
                    row["is_active"] = "Active" if row.get("is_active") is True else ("Inactive" if row.get("is_active") is False else "Unknown")
                    writer.writerow(row)
                
                return web.Response(
                    text=output.getvalue(),
                    content_type="text/csv",
                    headers={
                        "Content-Disposition": f"attachment; filename=facebook_posts_{len(post_ids)}.csv"
                    }
                )
            
            elif action == "delete":
                with fb_db.pool.cursor() as cur:
                    placeholders = ",".join(["%s"] * len(post_ids))
                    # Delete comments first (FK constraint)
                    cur.execute(f"DELETE FROM facebook.comments WHERE post_id IN ({placeholders})", tuple(post_ids))
                    cur.execute(f"DELETE FROM facebook.posts WHERE post_id IN ({placeholders})", tuple(post_ids))
                return web.json_response({"status": "ok", "deleted": len(post_ids)})
            
            else:
                return web.json_response({"status": "error", "message": f"Unknown action: {action}"}, status=400)
        
        except Exception as e:
            logger.error(f"Error in bulk action: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_bulk_status(self, request: web.Request) -> web.Response:
        """Get progress of a bulk operation."""
        task_id = request.query.get("task_id", "")
        progress = self._bulk_progress.get(task_id, {"status": "unknown", "message": "Task not found"})
        return web.json_response({"status": "ok", "progress": progress})

    async def _handle_save_cookie(self, request: web.Request) -> web.Response:
        """Save a manually provided Facebook cookie to in-memory store (segregated by client_id)."""
        try:
            data = await request.json()
            cookie_str = data.get("cookie", "").strip()
            user_agent = data.get("user_agent", "").strip()
            fb_dtsg = data.get("fb_dtsg", "").strip()
            lsd = data.get("lsd", "").strip()
            client_id = data.get("client_id") or request.headers.get("X-Client-ID") or "default"
            
            from proxify.platforms.facebook.auth import IN_MEMORY_TEMPLATES, TENANT_TEMPLATES
            tenant_cookie = TENANT_COOKIES.setdefault(client_id, {})
            tenant_templates = TENANT_TEMPLATES.setdefault(client_id, {})
            
            feed_template = data.get("feed_template")
            tpl_cookie = ""
            friendly_name = data.get("friendly_name", "Unknown")
            if "feed_template" in data:
                # 1. Capture cookie string from headers
                tpl_cookie = data["feed_template"]["headers"].get("cookie", "") or data["feed_template"]["headers"].get("Cookie", "")
                
                feed_template = data["feed_template"]
                
                if "Depth" in friendly_name or "Reply" in friendly_name:
                    tenant_templates["reply"] = feed_template
                    IN_MEMORY_TEMPLATES["reply"] = feed_template
                    logger.debug(f"[Extension] Saved Reply template for '{client_id}': {friendly_name}")
                elif "Comment" in friendly_name or "UFI" in friendly_name:
                    tenant_templates["comment"] = feed_template
                    IN_MEMORY_TEMPLATES["comment"] = feed_template
                    logger.debug(f"[Extension] Saved Comment template for '{client_id}': {friendly_name}")
                else:
                    tenant_templates["feed"] = feed_template
                    IN_MEMORY_TEMPLATES["feed"] = feed_template
                    logger.debug(f"[Extension] Saved Feed template for '{client_id}': {friendly_name}")

                if tpl_cookie:
                    current_cookie = tenant_cookie.get("cookie", "")
                    if "xs=" in tpl_cookie and "xs=" not in current_cookie:
                        import re
                        xs_match = re.search(r'xs=([^;]+)', tpl_cookie)
                        if xs_match and current_cookie:
                            tenant_cookie["cookie"] = f"{current_cookie}; xs={xs_match.group(1)}"
                            IN_MEMORY_COOKIES["cookie"] = tenant_cookie["cookie"]
                            logger.debug("[Extension] Merged missing xs cookie into in-memory cookies from template!")
                        else:
                            tenant_cookie["cookie"] = tpl_cookie
                            IN_MEMORY_COOKIES["cookie"] = tpl_cookie
                    elif not current_cookie:
                        tenant_cookie["cookie"] = tpl_cookie
                        IN_MEMORY_COOKIES["cookie"] = tpl_cookie

            sd = data.get("sd", None)
            cookie_names = data.get("cookie_names", [])
            
            log_cookie = cookie_str if cookie_str else tpl_cookie
            logger.debug(f"[Extension] Received cookie (client={client_id}) len={len(log_cookie)}, UA={bool(user_agent)}, fb_dtsg={bool(fb_dtsg)}, lsd={bool(lsd)}")
            
            if not cookie_str and not feed_template:
                return web.json_response({"status": "error", "message": "No cookie or template provided"}, status=400)

            user_id = data.get("user_id", "").strip()
            if user_id:
                tenant_cookie["user_id"] = user_id
                IN_MEMORY_COOKIES["user_id"] = user_id
                if cookie_str and "c_user=" not in cookie_str:
                    cookie_str = f"c_user={user_id}; {cookie_str}"

            if cookie_str:
                if "xs=" not in cookie_str and "xs=" in tenant_cookie.get("cookie", ""):
                    import re
                    xs_match = re.search(r'xs=([^;]+)', tenant_cookie["cookie"])
                    if xs_match:
                        cookie_str = f"{cookie_str}; xs={xs_match.group(1)}"
                        logger.info("[Extension] Preserved existing xs cookie in merged cookie string")

                tenant_cookie["cookie"] = cookie_str
                IN_MEMORY_COOKIES["cookie"] = cookie_str
                try:
                    from proxify.platforms.facebook.database import fb_db
                    fb_db.config.set("fb_cookie", cookie_str)
                    if user_id:
                        fb_db.config.set("fb_user_id", user_id)
                except Exception as e:
                    logger.debug(f"[Extension] Error persisting cookie to config: {e}")
            if user_agent:
                tenant_cookie["user_agent"] = user_agent
                IN_MEMORY_COOKIES["user_agent"] = user_agent
            if fb_dtsg:
                tenant_cookie["fb_dtsg"] = fb_dtsg
                IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg
                try:
                    from proxify.platforms.facebook.database import fb_db
                    fb_db.config.set("fb_dtsg", fb_dtsg)
                except Exception:
                    pass
            if lsd:
                tenant_cookie["lsd"] = lsd
                IN_MEMORY_COOKIES["lsd"] = lsd
                try:
                    from proxify.platforms.facebook.database import fb_db
                    fb_db.config.set("lsd", lsd)
                except Exception:
                    pass
            if sd:
                tenant_cookie["sd"] = sd
                IN_MEMORY_COOKIES["sd"] = sd
                
            final_cookie = tenant_cookie.get("cookie", "")
            has_c_user = "c_user=" in final_cookie or bool(user_id)
            has_xs = "xs=" in final_cookie

            # Pre-synthesize feed template if not present so crawler is primed immediately
            if "feed" not in tenant_templates:
                try:
                    from proxify.platforms.facebook.crawler import _default_crawler
                    _default_crawler._synthesize_feed_template(group_id="", raw_cookie=final_cookie, client_id=client_id)
                except Exception as e:
                    logger.debug(f"[API] Error pre-synthesizing feed template: {e}")
            
            if has_c_user and has_xs and bool(fb_dtsg):
                msg = f"✅ Đồng bộ HOÀN HẢO (Client: {client_id}). Sẵn sàng crawl!"
            elif has_c_user and bool(fb_dtsg):
                msg = f"⚠️ Đã lưu UID & fb_dtsg (Client: {client_id}). Hệ thống sẽ dùng Extension Tab để xác thực."
            elif cookie_str:
                msg = f"✅ Cookie đã lưu ({len(cookie_str)} ký tự cho {client_id})."
            else:
                msg = f"✅ Đã lưu template {friendly_name} từ extension ({client_id})."
                
            return web.json_response({
                "status": "ok", 
                "message": msg,
                "client_id": client_id,
                "has_xs": has_xs,
                "has_c_user": has_c_user,
                "has_dtsg": bool(fb_dtsg)
            })
        except Exception as e:
            logger.error(f"Error saving cookie: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_get_cookie(self, request: web.Request) -> web.Response:
        """Get the saved cookie string from memory for a specific client."""
        try:
            client_id = request.query.get("client_id") or request.headers.get("X-Client-ID") or "default"
            tenant_cookie = TENANT_COOKIES.get(client_id, {})
            cookie_str = tenant_cookie.get("cookie", "") or IN_MEMORY_COOKIES.get("cookie", "")
            return web.json_response({"status": "ok", "cookie": cookie_str, "client_id": client_id})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)
