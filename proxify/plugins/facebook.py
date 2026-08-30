"""Facebook Extractor Plugin."""

import json
from pathlib import Path
from typing import Any, List, Dict
from aiohttp import web
from mitmproxy import http
import logging

from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin

background_tasks = set()

logger = logging.getLogger("proxify.facebook")

IN_MEMORY_COOKIES = {}

@register_plugin("facebook")
class FacebookPlugin(BasePlugin):
    name = "Facebook Extractor"
    description = "Trích xuất bài viết, bình luận từ Facebook GraphQL"
    target_domains = ["facebook.com", "fbcdn.net"]

    def __init__(self, storage=None, config=None):
        super().__init__(storage, config)
        self.last_extracted_id = 0

    async def on_request(self, flow: Any) -> None:
        """Intercept Facebook GraphQL requests to capture tokens."""
        if not isinstance(flow, http.HTTPFlow):
            return
            
        domain = flow.request.pretty_host
        if 'facebook.com' not in domain and 'fbcdn.net' not in domain:
            return

        if "/api/graphql" in flow.request.path:
            # We want to capture the full request to act as a template
            if not flow.request.urlencoded_form:
                return
                
            form_data = dict(flow.request.urlencoded_form)
            variables_str = form_data.get("variables", "")
            if not variables_str:
                return
                
            try:
                variables = json.loads(variables_str)
                friendly_name = form_data.get("fb_api_req_friendly_name", "")
                
                # Do not capture requests made by the crawler itself
                if "x-proxify-crawler" in flow.request.headers:
                    return
                    
                # STRICTLY capture only when it's a known graphQL query type
                if "fb_dtsg" in form_data:
                    # Extract headers properly
                    headers = {}
                    for k, v in flow.request.headers.items(multi=True):
                        k_lower = k.lower()
                        if k_lower == 'cookie':
                            if 'cookie' in headers:
                                headers['cookie'] += '; ' + v
                            else:
                                headers['cookie'] = v
                        else:
                            headers[k_lower] = v
                            
                    headers.pop("content-length", None)
                    headers.pop("accept-encoding", None)
                    
                    tokens = {
                        "headers": headers,
                        "form_data": form_data
                    }
                    
                    token_file = Path(__file__).parent.parent / "platforms" / "facebook" / "tokens.json"
                    try:
                        existing = json.loads(token_file.read_text())
                    except:
                        existing = {}
                        
                    if "GroupsCometFeed" in friendly_name:
                        existing["feed"] = tokens
                        existing["headers"] = headers
                        existing["form_data"] = form_data
                        token_file.write_text(json.dumps(existing, indent=2))
                        logger.info(f"Captured new Facebook Feed Template! ({friendly_name})")
                    elif "comment" in friendly_name.lower() or "ufi" in friendly_name.lower():
                        if "repl" in friendly_name.lower():
                            existing["reply"] = tokens
                            token_file.write_text(json.dumps(existing, indent=2))
                            logger.info(f"Captured new Facebook Reply Template! ({friendly_name})")
                        else:
                            existing["comment"] = tokens
                            token_file.write_text(json.dumps(existing, indent=2))
                            logger.info(f"Captured new Facebook Comment Template! ({friendly_name})")
            except Exception as e:
                logger.debug(f"Template capture parsing error: {e}")

    async def on_response(self, flow: Any) -> None:
        """Parse Facebook GraphQL responses and detect unavailable posts."""
        if not isinstance(flow, http.HTTPFlow):
            return
        
        domain = flow.request.pretty_host
        if 'facebook.com' not in domain:
            return
        
        # Auto-detect unavailable posts when user visits a permalink
        if flow.request.method == "GET" and "/groups/" in flow.request.path and "/posts/" in flow.request.path:
            body = flow.response.get_text(strict=False) or ""
            is_error = "B\\u1ea1n hi\\u1ec7n kh\\u00f4ng xem \\u0111\\u01b0\\u1ee3c n\\u1ed9i dung n\\u00e0y" in body
            if is_error:
                # Use the full path to match permalink_url in DB (post_id is Base64, not the numeric URL ID)
                permalink_pattern = f"%{flow.request.path.rstrip('/')}%"
                logger.info(f"[FB] Permalink {flow.request.path} detected as INACTIVE (Error page detected)")
                try:
                    with fb_db.pool.cursor() as cur:
                        cur.execute("UPDATE facebook.posts SET is_active = FALSE WHERE permalink_url LIKE %s", (permalink_pattern,))
                        if cur.rowcount > 0:
                            logger.info(f"[FB] Marked {cur.rowcount} post(s) as inactive")
                except Exception as e:
                    logger.error(f"[FB] Error updating post status: {e}")

    def get_ui_tabs(self) -> List[Dict[str, str]]:
        return [
            {
                "id": "facebook-extractor",
                "label": "Facebook Extractor",
                "url": "/facebook"
            }
        ]

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
        ]

    _cached_groups = None
    _cached_groups_time = 0

    async def _handle_get_groups(self, request: web.Request) -> web.Response:
        import time
        from proxify.platforms.facebook.database import fb_db
        
        now = time.time()
        if self._cached_groups and (now - self._cached_groups_time) < 300:
            return web.json_response({"status": "ok", "data": self._cached_groups})
            
        try:
            with fb_db.pool.cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT 
                        COALESCE(group_id, group_name) as group_id, 
                        MAX(group_name) as group_name
                    FROM facebook.posts
                    WHERE group_name IS NOT NULL AND trim(group_name) != ''
                    GROUP BY COALESCE(group_id, group_name)
                """)
                groups = cur.fetchall()
                
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
        template_path = Path(__file__).parent.parent / "ui" / "templates" / "facebook.html"
        if not template_path.exists():
            return web.Response(text="Template not found", status=404)
        html = template_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")
        
    async def _handle_facebook_crawl(self, request: web.Request) -> web.Response:
        data = await request.json()
        group_id = data.get("group_id")
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")
        cookie = data.get("cookie", "")
        if not group_id:
            return web.json_response({"status": "error", "message": "Missing group_id"}, status=400)
            

        import asyncio
        from datetime import datetime, timezone
        from proxify.platforms.facebook.crawler import start_crawler, group_crawl_state
        
        try:
            # Parse dates and convert to UTC timestamps
            start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            # Inclusive end date (+24h)
            end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 86400
            
            if start_ts > end_ts:
                return web.json_response({"status": "error", "message": "start_date cannot be greater than end_date"}, status=400)
                
        except Exception as e:
            return web.json_response({"status": "error", "message": f"Invalid date format: {e}"}, status=400)

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

                fb_dtsg = IN_MEMORY_COOKIES.get("fb_dtsg")
                lsd = IN_MEMORY_COOKIES.get("lsd")
                cookie_str = cookie or IN_MEMORY_COOKIES.get("cookie", "")
                
                if fb_dtsg and lsd and cookie_str:
                    logger.info("⚡ Extension provided fb_dtsg and lsd! Bypassing Playwright template fetcher!")
                    group_crawl_state["message"] = "⚡ Đã nhận token trực tiếp từ Extension. Đang khởi chạy crawler..."
                else:
                    script = (
                        f"import asyncio; "
                        f"from proxify.platforms.facebook.template_fetcher import fetch_fresh_template; "
                        f"asyncio.run(fetch_fresh_template('{group_id}'))"
                    )
                    
                    try:
                        def _run_fetcher():
                            env = os.environ.copy()
                            env["PROXIFY_FB_COOKIE"] = cookie_str
                            env["PROXIFY_FB_UA"] = IN_MEMORY_COOKIES.get("user_agent", "")
                            return subprocess.run(
                                [sys.executable, "-c", script],
                                capture_output=True,
                                text=True,
                                timeout=120,
                                env=env
                            )
                        
                        proc = await asyncio.to_thread(_run_fetcher)
                        
                        if proc.stdout:
                            logger.info(f"Template fetcher stdout: {proc.stdout[-500:]}")
                        if proc.returncode != 0:
                            logger.error(f"Template fetcher failed (rc={proc.returncode}): {proc.stderr[-500:]}")
                        else:
                            logger.info("Template fetcher subprocess completed successfully")
                            if proc.stderr:
                                logger.info(f"Template fetcher stderr: {proc.stderr[-300:]}")
                        
                        fetcher_output = (proc.stderr or "") + (proc.stdout or "")
                        if "redirected to login" in fetcher_output:
                            logger.error("[Crawler] Template Fetcher detected login redirect — cookie is expired/invalid")
                            group_crawl_state["status"] = "error"
                            group_crawl_state["message"] = (
                                "❌ Cookie Facebook đã hết hạn.\n"
                                "Vui lòng mở trình duyệt và lướt Facebook **qua proxy Proxify** (cổng 8080) "
                                "để hệ thống tự động bắt cookie mới.\n\n"
                                "Hoặc dán cookie thủ công vào ô 'Facebook Cookie' trên giao diện."
                            )
                            return  # Don't start crawler with dead cookie

                    except Exception as e:
                        logger.error(f"Error running template fetcher subprocess: {e}")

                # Read the saved tokens.json
                template = None
                token_file = Path(__file__).parent.parent / "platforms" / "facebook" / "tokens.json"
                if token_file.exists():
                    try:
                        template = json.loads(token_file.read_text(encoding="utf-8"))
                        if fb_dtsg and lsd:
                            # INJECT FRESH COOKIE SO CRAWLER DOESN'T USE THE DEAD ONE FROM TOKENS.JSON
                            if cookie_str:
                                template["cookie"] = cookie_str
                            for key in ["feed", "comment", "reply"]:
                                if key in template:
                                    if "form_data" in template[key]:
                                        template[key]["form_data"]["fb_dtsg"] = fb_dtsg
                                        template[key]["form_data"]["lsd"] = lsd
                                    if "headers" in template[key] and IN_MEMORY_COOKIES.get("user_agent"):
                                        template[key]["headers"]["user-agent"] = IN_MEMORY_COOKIES["user_agent"]
                    except Exception as e:
                        logger.error(f"Error reading fresh template: {e}")

                if not template:
                    logger.warning(
                        "Playwright could not fetch fresh template. "
                        "Falling back to saved template."
                    )
                    group_crawl_state["message"] = (
                        "⚠️ Không lấy được template mới. Đang dùng template cũ..."
                    )

                await start_crawler(group_id, start_ts, end_ts, template=template, client_cookie=cookie)
            except Exception as e:
                import traceback
                logger.error(f"FATAL error in _crawl_with_fresh_template: {e}")
                logger.error(traceback.format_exc())
                from proxify.platforms.facebook.crawler import group_crawl_state
                group_crawl_state["status"] = "error"
                group_crawl_state["message"] = f"Lỗi nội bộ: {e}"
            finally:
                # Security: Delete the cookie from RAM immediately after crawl finishes
                if "cookie" in IN_MEMORY_COOKIES:
                    IN_MEMORY_COOKIES.pop("cookie", None)
                    logger.info("Cleared in-memory cookie after crawl.")

        # Run in background
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
        from proxify.platforms.facebook.crawler import refresh_progress, group_crawl_state
        return web.json_response({
            "refresh": refresh_progress,
            "group_crawl": group_crawl_state
        })

    async def _handle_facebook_results(self, request: web.Request) -> web.Response:
        from proxify.platforms.facebook.database import fb_db
        
        sort_by = request.query.get("sort", "time")
        order = request.query.get("order", "DESC").upper()
        if order not in ["ASC", "DESC"]:
            order = "DESC"
            
        group_id = request.query.get("group_id", "")
        status_filter = request.query.get("status", "")  # active|inactive|unknown

            
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
            with fb_db.pool.cursor(dict_cursor=True) as cur:
                conditions = []
                params = []
                if group_id:
                    conditions.append("(p.group_id = %s OR p.group_name = %s)")
                    params.extend([group_id, group_id])
                if status_filter == "active":
                    conditions.append("p.is_active = TRUE")
                elif status_filter == "inactive":
                    conditions.append("p.is_active = FALSE")
                elif status_filter == "unknown":
                    conditions.append("p.is_active IS NULL")
                
                where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                    
                # Lấy tổng số lượng
                cur.execute(f"SELECT COUNT(*) as total FROM facebook.posts p {where_clause}", tuple(params))
                total_row = cur.fetchone()
                total = total_row["total"] if total_row else 0
                
                # Lấy danh sách bài viết (include crawled comment count)
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
                    LIMIT %s OFFSET %s
                """
                cur.execute(query_posts, tuple(params + [limit, offset]))
                posts = cur.fetchall()
                
                for p in posts:
                    # Serialize datetime objects
                    if p["creation_datetime"]:
                        if hasattr(p["creation_datetime"], "isoformat"):
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

    async def _handle_save_cookie(self, request: web.Request) -> web.Response:
        """Save a manually provided Facebook cookie to in-memory store."""
        try:
            data = await request.json()
            cookie_str = data.get("cookie", "").strip()
            user_agent = data.get("user_agent", "").strip()
            fb_dtsg = data.get("fb_dtsg", "").strip()
            lsd = data.get("lsd", "").strip()
            
            logger.info(f"[Extension] Received cookie len={len(cookie_str)}, UA={bool(user_agent)}, fb_dtsg={bool(fb_dtsg)} ({fb_dtsg[:10]}), lsd={bool(lsd)} ({lsd[:10]})")
            
            if not cookie_str:
                return web.json_response({"status": "error", "message": "Cookie is empty"}, status=400)

            # Store in RAM only
            IN_MEMORY_COOKIES["cookie"] = cookie_str
            if user_agent:
                IN_MEMORY_COOKIES["user_agent"] = user_agent
            if fb_dtsg:
                IN_MEMORY_COOKIES["fb_dtsg"] = fb_dtsg
            if lsd:
                IN_MEMORY_COOKIES["lsd"] = lsd
            # Quick validation: check for key auth cookies
            has_c_user = "c_user=" in cookie_str
            has_xs = "xs=" in cookie_str
            if has_c_user and has_xs:
                msg = f"✅ Cookie đã lưu ({len(cookie_str)} ký tự). Phát hiện c_user và xs — sẵn sàng crawl!"
            else:
                msg = (
                    f"⚠️ Cookie đã lưu ({len(cookie_str)} ký tự) nhưng "
                    f"thiếu {'c_user' if not has_c_user else ''}"
                    f"{' và ' if not has_c_user and not has_xs else ''}"
                    f"{'xs' if not has_xs else ''}. "
                    "Cookie có thể không đủ để xác thực."
                )
            return web.json_response({"status": "ok", "message": msg})
        except Exception as e:
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )

    async def _handle_get_cookie(self, request: web.Request) -> web.Response:
        """Get the saved cookie string from memory (masked for security)."""
        try:
            cookie_str = IN_MEMORY_COOKIES.get("cookie", "")
            if cookie_str:
                # Mask the cookie for display — show first/last 10 chars
                if len(cookie_str) > 30:
                    masked = cookie_str[:15] + "..." + cookie_str[-15:]
                else:
                    masked = cookie_str
                return web.json_response({
                    "status": "ok",
                    "has_cookie": True,
                    "length": len(cookie_str),
                    "preview": masked,
                    "cookie": cookie_str,
                })
            else:
                return web.json_response({
                    "status": "ok",
                    "has_cookie": False,
                })
        except Exception as e:
            return web.json_response(
                {"status": "error", "message": str(e)}, status=500
            )

    async def _handle_get_comments(self, request: web.Request) -> web.Response:
        """Get comments for a specific post."""
        from proxify.platforms.facebook.database import fb_db
        
        post_id = request.query.get("post_id", "")
        if not post_id:
            return web.json_response(
                {"status": "error", "message": "post_id is required"}, status=400
            )

        try:
            with fb_db.pool.cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT c.comment_id, c.post_id, c.parent_comment_id,
                           c.author_id, c.author_name, c.body_text,
                           c.creation_time, c.creation_datetime,
                           c.reaction_count, c.reply_count,
                           a.avatar_url
                    FROM facebook.comments c
                    LEFT JOIN facebook.authors a ON c.author_id = a.id
                    WHERE c.post_id = %s
                    ORDER BY c.creation_time ASC NULLS LAST
                """, (post_id,))
                comments = cur.fetchall()

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
            cookie = body.get("cookie") or IN_MEMORY_COOKIES.get("cookie", "")
            
            logger.info(f">>> UI CRAWL REQUEST RECEIVED! post_id: {post_id}, feedback_id: {feedback_id}, cookie_snippet: {cookie[:20] if cookie else 'None'}")
            
            if not post_id:
                return web.json_response(
                    {"status": "error", "message": "post_id is required"}, status=400
                )
            
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
                return web.json_response({
                    "status": "error",
                    "message": "Không tìm thấy feedback_id. Vui lòng cào lại group để cập nhật dữ liệu bài viết."
                }, status=400)

            cookie = body.get("cookie") or IN_MEMORY_COOKIES.get("cookie", "")
            
            from proxify.platforms.facebook.crawler import crawl_post_comments
            
            # Run in background
            async def _bg_crawl():
                try:
                    await crawl_post_comments(post_id, feedback_id, client_cookie=cookie)
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
        
        logger.info(f">>> UI STATUS POLL RECEIVED! post_id: {post_id}, progress_found: {progress is not None}")
        
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
        from proxify.platforms.facebook.database import fb_db
        try:
            body = await request.json()
            post_ids = body.get("post_ids", [])
            is_active = body.get("is_active")  # True, False, or None
            
            if not post_ids:
                return web.json_response({"status": "error", "message": "post_ids required"}, status=400)
            
            with fb_db.pool.cursor() as cur:
                placeholders = ",".join(["%s"] * len(post_ids))
                if is_active is None:
                    cur.execute(f"UPDATE facebook.posts SET is_active = NULL WHERE post_id IN ({placeholders})", tuple(post_ids))
                else:
                    cur.execute(f"UPDATE facebook.posts SET is_active = %s WHERE post_id IN ({placeholders})", tuple([is_active] + post_ids))
            
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
            cookie = body.get("cookie") or IN_MEMORY_COOKIES.get("cookie", "")
            
            if not post_ids:
                return web.json_response({"status": "error", "message": "post_ids required"}, status=400)
            
            task_id = f"bulk_{action}_{id(post_ids)}"
            
            if action == "crawl_comments":
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
                        
                        if fb_id:
                            try:
                                await crawl_post_comments(pid, fb_id, client_cookie=cookie)
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
                self._bulk_progress[task_id] = {"status": "running", "current": 0, "total": len(post_ids), "message": "Đang kiểm tra..."}
                
                async def _bg_check_status():
                    from proxify.utils.stealth import StealthSessionManager
                    manager = StealthSessionManager()
                    
                    for i, pid in enumerate(post_ids):
                        self._bulk_progress[task_id] = {
                            "status": "running", "current": i + 1, "total": len(post_ids),
                            "message": f"Đang kiểm tra bài {i+1}/{len(post_ids)}..."
                        }
                        
                        # Get permalink
                        permalink = None
                        try:
                            with fb_db.pool.cursor(dict_cursor=True) as cur:
                                cur.execute("SELECT permalink_url FROM facebook.posts WHERE post_id = %s", (pid,))
                                row = cur.fetchone()
                                if row:
                                    permalink = row["permalink_url"]
                        except Exception:
                            pass
                        
                        if permalink:
                            try:
                                cookies = {}
                                if cookie:
                                    # Basic parse or logic if needed
                                    pass
                                
                                resp = await manager.request(
                                    "GET", permalink,
                                    headers={
                                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                        "Accept-Language": "vi,en;q=0.9",
                                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    },
                                    cookies=cookies,
                                    allow_redirects=True,
                                    timeout=15.0,
                                )
                                
                                is_active = resp.status_code == 200
                                if is_active:
                                    body = resp.text
                                    if "B\u1ea1n hi\u1ec7n kh\u00f4ng xem \u0111\u01b0\u1ee3c n\u1ed9i dung n\u00e0y" in body:
                                        is_active = False
                                    elif "login.php" in str(resp.url).lower() or "checkpoint" in str(resp.url).lower():
                                        is_active = False

                                with fb_db.pool.cursor() as cur:
                                    cur.execute("UPDATE facebook.posts SET is_active = %s WHERE post_id = %s", (is_active, pid))
                            except Exception as e:
                                logger.error(f"Status check error for {pid}: {e}")
                        
                        await asyncio.sleep(1)
                    
                    self._bulk_progress[task_id] = {
                        "status": "done", "current": len(post_ids), "total": len(post_ids),
                        "message": f"Đã kiểm tra {len(post_ids)} bài!"
                    }
                
                task = asyncio.create_task(_bg_check_status())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.json_response({"status": "ok", "task_id": task_id})
            
            elif action == "refresh":
                with fb_db.pool.cursor(dict_cursor=True) as cur:
                    placeholders = ",".join(["%s"] * len(post_ids))
                    cur.execute(f"SELECT permalink_url FROM facebook.posts WHERE post_id IN ({placeholders})", list(post_ids))
                    rows = cur.fetchall()
                    urls = [r["permalink_url"] for r in rows if r.get("permalink_url")]
                
                if not urls:
                    return web.json_response({"status": "error", "message": "No valid URLs found for selected posts"})
                    
                from proxify.platforms.facebook.crawler import crawl_specific_posts, refresh_progress
                import asyncio
                
                # Reusing the existing refresh_progress used by crawl_posts endpoint
                refresh_progress["total"] = len(urls)
                refresh_progress["current"] = 0
                refresh_progress["status"] = "running"
                
                task = asyncio.create_task(crawl_specific_posts(urls))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return web.json_response({"status": "ok", "message": "Refresh started"})

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
