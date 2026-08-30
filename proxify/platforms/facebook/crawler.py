"""
Facebook Crawler — Facade
============================
Provides a unified API for all Facebook Group crawling operations.

Pattern: **Facade** — wraps StealthSessionManager, SessionStateManager,
DelayStrategy, CircuitBreaker, and TokenStore into a single clean interface.

The module-level aliases at the bottom maintain backward compatibility
with existing imports from ``plugins/facebook.py``.
"""

import asyncio
import json
import logging
import re
import urllib.parse
import time
from typing import Optional

from proxify.database import pool as shared_pool
from proxify.utils.stealth import StealthSessionManager, StealthRequestError
from proxify.utils.circuit_breaker import crawl_breaker
from proxify.platforms.facebook.delay import (
    CrawlDelayConfig,
    page_delay,
    comment_delay,
)
from proxify.platforms.facebook.session_state import SessionStateManager
from proxify.platforms.facebook.token_store import get_saved_tokens, get_cookies_and_ua_from_db, extract_templates
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper
from proxify.platforms.facebook.network import GlobalNetworkClient
from proxify.platforms.facebook.observer import state_observer
from proxify.platforms.facebook.commands import CrawlFeedCommand, RefreshCommand, CrawlCommentCommand

logger = logging.getLogger("proxify.facebook.crawler")

# ─── Constants ──────────────────────────────────────────────────────────

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"
INTERNAL_PROXY = "http://127.0.0.1:8080"
MAX_PAGES_PER_SESSION = 100000
CONCURRENCY_LIMIT = 1  # Phase 3: Single API Worker (Mutex)


async def _resolve_numeric_group_id(group_id_or_slug: str, cookie: str, manager) -> str:
    """Resolves a Facebook Group slug to its Numeric ID by fetching its HTML."""
    if group_id_or_slug.isdigit():
        return group_id_or_slug
        
    # Check DB cache first
    try:
        from proxify.platforms.facebook.database import fb_db
        with fb_db.pool.cursor(dict_cursor=True) as cur:
            cur.execute("SELECT group_id FROM facebook.groups WHERE slug = %s", (group_id_or_slug,))
            row = cur.fetchone()
            if row:
                return row["group_id"]
    except Exception as e:
        logger.warning(f"[Crawler] Lỗi đọc DB nhóm: {e}")

    import re
    url = f"https://www.facebook.com/groups/{group_id_or_slug}"
    try:
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept-encoding": "gzip, deflate"
        }
        if cookie:
            headers["cookie"] = cookie
            
        r = await manager.request("GET", url, headers=headers)
        if r and r.text:
            match = re.search(r'(?:groupID|group_id)["\'\\]*\s*:\s*["\'\\]*(\d+)', r.text)
            if match:
                numeric_id = match.group(1)
                # Cache into DB
                try:
                    with fb_db.pool.cursor() as cur:
                        cur.execute(
                            "INSERT INTO facebook.groups (group_id, slug) VALUES (%s, %s) ON CONFLICT (group_id) DO NOTHING",
                            (numeric_id, group_id_or_slug)
                        )
                except Exception:
                    pass
                return numeric_id
    except Exception as e:
        logger.warning(f"[Crawler] Lỗi phân giải slug {group_id_or_slug}: {e}")
    
    # Fallback to returning original if failed
    return group_id_or_slug

class FacebookCrawler:

    """Facade for Facebook Group crawling operations.

    Encapsulates:
    - ``StealthSessionManager``: TLS impersonation and retry logic
    - ``SessionStateManager``: Dynamic form parameter simulation
    - ``CrawlDelayConfig``: Human-like timing strategy
    - ``crawl_breaker``: Global circuit breaker for soft-block handling

    Usage::

        crawler = FacebookCrawler()
        await crawler.crawl_group_feed(group_id="123", start_ts=..., end_ts=...)
    """

    def __init__(
        self,
        manager: Optional[StealthSessionManager] = None,
        delay_config: Optional[CrawlDelayConfig] = None,
    ) -> None:
        self.network_client = GlobalNetworkClient(manager)
        self.delay_config = delay_config or CrawlDelayConfig()
        
        # Backward compatibility for existing code that checks crawler.crawl_state directly
        self.crawl_state = state_observer.crawl_state
        self.refresh_progress = state_observer.refresh_progress
        self._comment_progress = state_observer._comment_progress

        # Cache: group_id → group_name (detected once, reused for all pages)
        self._group_name_cache: dict[str, str] = {}
        
        # Internal Queue for single worker (Command Pattern)
        self._command_queue = asyncio.Queue()
        try:
            self._worker_task = asyncio.create_task(self._api_worker_loop())
        except RuntimeError:
            self._worker_task = None

    @property
    def manager(self) -> StealthSessionManager:
        return self.network_client.manager

    async def _api_worker_loop(self):
        """The single exclusive API worker. 
        Takes commands from the queue and executes them sequentially.
        Guarantees 100% no network overlapping (Mutex behavior).
        """
        while True:
            command = await self._command_queue.get()
            try:
                await command.execute()
            except Exception as e:
                logger.error(f"[Crawler Worker] Command failed: {e}")
            finally:
                self._command_queue.task_done()

    async def _safe_request(self, *args, **kwargs):
        """Wrapper that delegates to the GlobalNetworkClient."""
        return await self.network_client.safe_request(*args, **kwargs)

    # ═══════════════════════════════════════════════════════════════════
    #  Public API
    # ═══════════════════════════════════════════════════════════════════

    async def crawl_group_feed(
        self,
        group_id: str,
        start_timestamp: int,
        end_timestamp: int,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
        reset_cursor: bool = True,
    ) -> None:
        """Facade: Enqueues a CrawlFeedCommand to the API worker."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._api_worker_loop())
        cmd = CrawlFeedCommand(self, group_id, start_timestamp, end_timestamp, template, client_cookie, reset_cursor)
        await self._command_queue.put(cmd)

    async def _execute_crawl_group_feed(
        self,
        group_id: str,
        start_timestamp: int,
        end_timestamp: int,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
        reset_cursor: bool = True,
    ) -> None:
        """Start the background group feed crawler.

        Args:
            group_id: Facebook Group ID to crawl.
            start_timestamp: Unix timestamp for date range start.
            end_timestamp: Unix timestamp for date range end.
            template: Pre-fetched template dict. Falls back to saved file.
            client_cookie: User-provided cookie string (highest priority).
        """
        # ── Load templates ──────────────────────────────────────────
        tokens = template or await get_saved_tokens()
        if not tokens:
            logger.error("No FB template found. Browse a Facebook Group through Proxify first.")
            return

        feed_tpl, comment_tpl, reply_tpl = extract_templates(tokens)
        if not feed_tpl or "form_data" not in feed_tpl:
            logger.error("No FB Feed template found. Browse a Facebook Group through Proxify first.")
            return

        logger.info(
            f"Starting crawler for Group {group_id}, "
            f"date_range=[{start_timestamp}, {end_timestamp}]"
        )

        # ── Resolve cookie ──────────────────────────────────────────
        raw_cookie = await self._resolve_cookie(client_cookie, tokens)

        numeric_group_id = await _resolve_numeric_group_id(group_id, raw_cookie, self.manager)
        if numeric_group_id != group_id:
            logger.info(f"Resolved group slug '{group_id}' -> Numeric ID '{numeric_group_id}'")
            # Keep original group_id for DB matching, use numeric_group_id for GraphQL calls
        if not raw_cookie:
            self.crawl_state.update(
                status="error",
                message="❌ Không tìm thấy cookies Facebook.\nHãy paste cookie vào ô 'Facebook Cookie' trên giao diện.",
            )
            return

        # ── Prepare headers & state ─────────────────────────────────
        self.crawl_state.update(
            status="running",
            group_id=group_id,
            message=f"[SUCCESS] Tiến trình đang chạy ngầm cho Group ID: {group_id}...\nDữ liệu sẽ tự động xuất hiện bên dưới.",
        )

        headers = self._build_headers(feed_tpl, raw_cookie, group_id)
        form_data_template = feed_tpl.get("form_data", {})
        session_state = SessionStateManager()

        # ── Pagination loop ─────────────────────────────────────────
        from proxify.platforms.facebook.database import fb_db
        cursor = "" if reset_cursor else (fb_db.config.get(f"crawl_cursor_{group_id}") or "")
        consecutive_old_pages = 0

        for page_num in range(MAX_PAGES_PER_SESSION):
            # Circuit breaker gate
            if not crawl_breaker.allow_request():
                remaining = crawl_breaker.remaining_cooldown
                logger.warning(f"[Crawler] Circuit breaker OPEN — cooldown: {remaining / 60:.0f}min")
                self.crawl_state.update(
                    status="paused",
                    message=f"⚠️ Phát hiện block từ Facebook. Tạm dừng crawl.\nTự động tiếp tục sau {remaining / 60:.0f} phút.",
                )
                break

            # Build form data with dynamic session params
            data = form_data_template.copy()
            session_state.update_params(data)
            cursor = self._set_variables(data, numeric_group_id, cursor)
            if cursor is None:  # parse error
                break

            try:
                self.crawl_state.update(
                    message=f"🚀 Đang thu thập trang {page_num + 1}...\nChờ xíu nha!",
                    last_p_count=0,
                    last_c_count=0,
                    updated_at=time.time()
                )
                logger.info(f"[Crawler] Page {page_num + 1}, cursor: {cursor[:50]}...")
                resp = await self._safe_request(
                    "POST", GRAPHQL_ENDPOINT,
                    headers=headers,
                    data=urllib.parse.urlencode(data).encode(),
                    
                )
                resp_text = resp.text
                collected = [resp_text]

                logger.info(
                    f"[Crawler] Page {page_num + 1}: status={resp.status_code}, "
                    f"len={len(resp_text)}, blocked={resp.is_blocked}"
                )

                # Check for Facebook JSON errors (e.g., auth failure 1357001)
                stripped_resp = resp_text.strip()
                if stripped_resp.startswith("for (;;);"):
                    try:
                        first_line = stripped_resp.split('\n')[0]
                        json_data = json.loads(first_line[9:])
                        if "error" in json_data and isinstance(json_data["error"], int):
                            error_code = json_data["error"]
                            error_summary = json_data.get("errorSummary", "Unknown error")
                            logger.error(f"[Crawler] GraphQL error {error_code}: {error_summary}")
                            if error_code == 1357001:
                                self.crawl_state.update(
                                    status="error",
                                    message="❌ Cookie đã hết hạn hoặc bị lỗi xác thực (Error 1357001).\nVui lòng cập nhật lại cookie mới.",
                                )
                            else:
                                self.crawl_state.update(
                                    status="error",
                                    message=f"❌ Lỗi truy vấn Facebook (Code {error_code}): {error_summary}\nVui lòng kiểm tra lại Cookie/Tài khoản.",
                                )
                            break
                    except Exception as e:
                        logger.error(f"[Crawler] Error parsing GraphQL JSON for error check: {e}, snippet: {resp_text[:100]}")
                        pass

                # Soft-block → trip circuit breaker and stop
                if resp.is_blocked:
                    crawl_breaker.trip(f"Soft-block on page {page_num + 1} (status={resp.status_code})")
                    self.crawl_state.update(
                        status="blocked",
                        message=f"🛑 Facebook đã block request ở page {page_num + 1}.\nCrawler đã dừng. Cooldown {crawl_breaker.remaining_cooldown / 60:.0f} phút.",
                    )
                    break

                crawl_breaker.record_success()

                # Check for old posts → stop condition
                should_stop, consecutive_old_pages, timestamps = self._check_old_posts(
                    resp_text, start_timestamp, consecutive_old_pages,
                )
                if should_stop:
                    logger.info("[Crawler] Reached old posts threshold. Stopping.")
                    break

                # Extract next cursor
                cursor = self._extract_cursor(resp_text)
                if not cursor:
                    logger.info("[Crawler] No more cursor. Stopping.")
                    fb_db.config.set(f"crawl_cursor_{group_id}", "")
                    break
                else:
                    fb_db.config.set(f"crawl_cursor_{group_id}", cursor)

                # Fetch comments & replies
                if comment_tpl:
                    await self._fetch_comments_for_page(
                        resp_text, comment_tpl, reply_tpl, collected,
                    )

                # Extract data from collected responses
                try:
                    variables = json.loads(data.get("variables", "{}"))
                    cached_name = self._group_name_cache.get(group_id)
                    p_count, c_count, detected_name = extract_from_responses(
                        collected, variables,
                        group_id=group_id,
                        group_name=cached_name,
                        start_ts=start_timestamp,
                        end_ts=end_timestamp,
                    )
                    # Cache detected name for all subsequent pages
                    if detected_name and not cached_name:
                        self._group_name_cache[group_id] = detected_name
                        logger.info(f"[Crawler] Cached group_name: {detected_name}")
                    logger.info(f"[Crawler] Page {page_num + 1}: {p_count} posts, {c_count} comments")
                    
                    # Format progress date
                    progress_msg = ""
                    if timestamps:
                        import statistics
                        from datetime import datetime
                        # Dùng median thay vì min để tránh trường hợp 1 bài cũ bị cmt đẩy lên (bump) làm sai lệch tiến độ
                        median_ts = statistics.median(timestamps)
                        median_date = datetime.fromtimestamp(median_ts).strftime('%d/%m/%Y')
                        progress_msg = f"\n(Đang quét bài viết quanh ngày {median_date})"
                    
                    self.crawl_state.update(
                        message=f"🚀 Đang thu thập trang {page_num + 1}...{progress_msg}",
                        last_p_count=p_count,
                        last_c_count=c_count,
                        updated_at=time.time()
                    )
                except Exception as e:
                    logger.error(f"[Crawler] Extraction failed: {e}")

                # Human-like delay
                delay = page_delay(self.delay_config)
                logger.info(f"[Crawler] Delay: {delay:.1f}s")
                await asyncio.sleep(delay)

            except StealthRequestError as e:
                logger.error(f"[Crawler] Request failed: {e}")
                await asyncio.sleep(10)
                continue
            except Exception as e:
                logger.error(f"[Crawler] Unexpected error: {e}")
                break

        # ── Finish ──────────────────────────────────────────────────
        stats = self.manager.stats
        logger.info(
            f"Crawler finished. requests={stats['total_requests']}, "
            f"blocks={stats['total_blocks']}, block_rate={stats['block_rate']}"
        )
        self.crawl_state.update(
            status="idle",
            message=f"Hoàn tất thu thập cho Group ID: {group_id}",
        )

    async def crawl_specific_posts(self, urls: list[str], template: Optional[dict] = None, client_cookie: Optional[str] = None) -> dict:
        """Facade: Enqueues a RefreshCommand to the API worker."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._api_worker_loop())
        cmd = RefreshCommand(self, urls, template, client_cookie)
        await self._command_queue.put(cmd)
        return {"status": "ok", "message": "Crawler queued"}

    async def _execute_crawl_specific_posts(self, urls: list[str], template: Optional[dict] = None, client_cookie: Optional[str] = None) -> dict:
        """Crawl specific post URLs to refresh metrics (reactions, comments).

        Args:
            urls: List of Facebook post permalink URLs.
            template: Optional tokens dict
            client_cookie: Optional cookie string from client

        Returns:
            Status dict with ``status`` and ``message`` keys.
        """
        from proxify.platforms.facebook.token_store import parse_cookie_string
        tokens = template or await get_saved_tokens() or {}
        raw_cookie = await self._resolve_cookie(client_cookie, tokens)
        
        user_agent = ""
        if tokens and "headers" in tokens:
            user_agent = tokens["headers"].get("user-agent", "")
            
        cookies = parse_cookie_string(raw_cookie) if raw_cookie else None

                
        if not user_agent:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
        if not cookies:
            logger.error("[Crawler] No cookies found.")
            return {"status": "error", "message": "No authentication cookies found"}

        logger.info(f"[Crawler] Refreshing {len(urls)} posts in parallel (Concurrency={CONCURRENCY_LIMIT})")
        self.refresh_progress.update(total=len(urls), current=0, status="running")

        try:
            sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
            
            async def _refresh_url(url: str, idx: int):
                async with sem:
                    self.refresh_progress["current"] = min(self.refresh_progress["current"] + 1, len(urls))
                    try:
                        resp = await self._safe_request(
                            "GET", url,
                            headers={
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": "vi,en;q=0.9",
                                "User-Agent": user_agent,
                            },
                            cookies=cookies,
                            
                            allow_redirects=True,
                            timeout=15.0,
                        )

                        if resp.is_blocked:
                            logger.warning(f"[Crawler] Blocked for {url}, skipping")
                            return

                        # Check if post is deleted/unavailable
                        if "B\\u1ea1n hi\\u1ec7n kh\\u00f4ng xem \\u0111\\u01b0\\u1ee3c n\\u1ed9i dung n\\u00e0y" in resp.text:
                            logger.info(f"[Crawler] Post {url} is INACTIVE (Error page detected)")
                            try:
                                with shared_pool.cursor() as cur:
                                    cur.execute("UPDATE facebook.posts SET is_active = FALSE WHERE permalink_url = %s", (url,))
                            except Exception as e:
                                logger.error(f"[Crawler] DB update failed for inactive {url}: {e}")
                            return

                        self._update_post_metrics(url, resp.text)

                    except StealthRequestError as e:
                        logger.error(f"[Crawler] Error fetching {url}: {e}")
                    except Exception as e:
                        logger.error(f"[Crawler] Unexpected error for {url}: {e}")

            await asyncio.gather(*[_refresh_url(u, i) for i, u in enumerate(urls)])

            logger.info("[Crawler] Refresh finished.")
            return {"status": "ok", "message": "Crawler finished"}

        except Exception as e:
            logger.error(f"[Crawler] Fatal error: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self.refresh_progress["status"] = "idle"

    # ═══════════════════════════════════════════════════════════════════
    #  Private Helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    async def _resolve_cookie(client_cookie: Optional[str], tokens: dict) -> str:
        """Resolve cookie string from available sources (priority chain).
        Priority:
        1. client_cookie (user provided)
        2. Database (most recent live login)
        3. tokens.json (cached template cookie)
        """
        if client_cookie:
            logger.info("[Crawler] Using user-provided fallback cookie")
            return client_cookie.strip()

        from proxify.platforms.facebook.token_store import get_cookies_and_ua_from_db
        db_cookie, _ = await get_cookies_and_ua_from_db(shared_pool)
        if db_cookie:
            logger.info("[Crawler] Using live-intercepted cookie from database")
            return db_cookie.strip()

        logger.error("[Crawler] No cookies found!")
        return ""

    @staticmethod
    def _build_headers(feed_tpl: dict, cookie: str, group_id: str) -> dict:
        """Build request headers from template, fixing anti-detection issues."""
        headers = feed_tpl.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["cookie"] = cookie
        headers["referer"] = f"https://www.facebook.com/groups/{group_id}"
        
        # DONT pop user-agent! Facebook checks UA strictly. We MUST use the user's real UA.
        # If it's missing, curl_cffi will auto-set it anyway.
        return headers

    @staticmethod
    def _set_variables(data: dict, group_id: str, cursor: str) -> Optional[str]:
        """Set GraphQL variables in form data. Returns cursor or None on error."""
        try:
            variables = json.loads(data.get("variables", "{}"))
            
            # Ép Facebook trả về danh sách theo thứ tự Thời gian đăng (Bài mới nhất - CHRONOLOGICAL)
            # Thay vì mặc định là "Hoạt động mới nhất" (Bài cũ nhưng có người mới comment sẽ bị đẩy lên)
            variables["sortingSetting"] = "CHRONOLOGICAL"
            
            if "id" in variables:
                variables["id"] = group_id
            if cursor:
                variables["cursor"] = cursor
            else:
                variables.pop("cursor", None)
            data["variables"] = json.dumps(variables, separators=(",", ":"))
            return cursor
        except Exception as e:
            logger.error(f"[Crawler] Failed to parse variables: {e}")
            return None

    @staticmethod
    def _check_old_posts(
        resp_text: str, start_ts: int, consecutive: int,
    ) -> tuple[bool, int, list[int]]:
        """Check if response contains posts older than start_ts.

        Returns (should_stop, updated_consecutive_count, timestamps).
        """
        timestamps = []
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                from proxify.platforms.facebook.extractor import DataHelper
                for rp in DataHelper.extract_nodes(obj, "Story"):
                    t = rp.get("creation_time")
                    if t:
                        try:
                            timestamps.append(int(t))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        if not timestamps:
            return False, consecutive, []

        # If ALL posts on this page are older than start_ts, increment consecutive counter.
        # We require at least 3 consecutive pages of old posts to stop.
        # This prevents stopping prematurely if the first few pages contain many Pinned Posts
        # that are very old, guaranteeing we've reached the actual timeline.
        if all(t < start_ts for t in timestamps):
            consecutive += 1
            if consecutive >= 3:
                return True, consecutive, timestamps
        else:
            consecutive = 0

        return False, consecutive, timestamps

    @staticmethod
    def _extract_cursor(resp_text: str) -> str:
        """Extract pagination cursor from GraphQL response."""
        match = re.search(r'"(?:end_)?cursor"\s*:\s*"([^"]+)"', resp_text)
        return match.group(1) if match else ""

    async def _fetch_comments_for_page(
        self,
        resp_text: str,
        comment_tpl: dict,
        reply_tpl: Optional[dict],
        collected: list[str],
    ) -> None:
        """Fetch comments and replies for all stories in a page response."""
        feedback_ids = self._extract_feedback_ids(resp_text)
        if not feedback_ids:
            return

        sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def _process(fid: str) -> None:
            async with sem:
                logger.info(f"[Crawler] Fetching comments for {fid}")
                c_ids, c_text = await self._fetch_comments(fid, comment_tpl)
                if c_text:
                    collected.append(c_text)
                if reply_tpl and c_ids:
                    for cid in c_ids:
                        logger.info(f"[Crawler] Fetching replies for {cid}")
                        r_text = await self._fetch_replies(cid, reply_tpl)
                        if r_text:
                            collected.append(r_text)
                        await asyncio.sleep(comment_delay(self.delay_config))
                await asyncio.sleep(comment_delay(self.delay_config))

        await asyncio.gather(*(_process(fid) for fid in feedback_ids))

    @staticmethod
    def _extract_feedback_ids(resp_text: str) -> list[str]:
        """Extract unique feedback IDs from stories in the response."""
        ids: list[str] = []
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                for story in DataHelper.extract_nodes(obj, "Story"):
                    feedback = story.get("feedback")
                    if isinstance(feedback, dict) and feedback.get("id"):
                        ids.append(feedback["id"])
            except Exception:
                pass
        return list(set(ids))

    async def _fetch_comments(
        self, feedback_id: str, template: dict,
    ) -> tuple[list[str], str]:
        """Fetch comment IDs for a post feedback_id."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        data = template.get("form_data", {}).copy()

        try:
            variables = json.loads(data.get("variables", "{}"))
            if "comments_target_id" in variables:
                variables["comments_target_id"] = feedback_id
            elif "feedback_id" in variables:
                variables["feedback_id"] = feedback_id
            elif "id" in variables:
                variables["id"] = feedback_id
            
            # Reset pagination cursors so we get the first page for this post
            for key in ["commentsAfterCursor", "commentsBeforeCursor", "cursor", "after", "before"]:
                if key in variables:
                    variables[key] = None
                
            data["variables"] = json.dumps(variables, separators=(",", ":"))
        except Exception:
            pass

        try:
            resp = await self._safe_request(
                "POST", GRAPHQL_ENDPOINT,
                headers=headers,
                data=urllib.parse.urlencode(data).encode(),
                
            )
            comment_ids = self._parse_comment_ids(resp.text)
            return comment_ids, resp.text
        except StealthRequestError as e:
            logger.error(f"[Crawler] Comment fetch failed for {feedback_id}: {e}")
            return [], ""

    async def _fetch_replies(self, comment_id: str, template: dict) -> str:
        """Fetch replies for a comment."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        data = template.get("form_data", {}).copy()

        try:
            variables = json.loads(data.get("variables", "{}"))
            if "comment_id" in variables:
                variables["comment_id"] = comment_id
            
            # Reset pagination cursors
            for key in ["commentsAfterCursor", "commentsBeforeCursor", "cursor", "after", "before"]:
                if key in variables:
                    variables[key] = None
                    
            data["variables"] = json.dumps(variables, separators=(",", ":"))
        except Exception:
            pass

        try:
            resp = await self._safe_request(
                "POST", GRAPHQL_ENDPOINT,
                headers=headers,
                data=urllib.parse.urlencode(data).encode(),
                
            )
            return resp.text
        except StealthRequestError as e:
            logger.error(f"[Crawler] Reply fetch failed for {comment_id}: {e}")
            return ""

    @staticmethod
    def _parse_comment_ids(resp_text: str) -> list[str]:
        """Parse comment IDs from a GraphQL response."""
        comment_ids: list[str] = []
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                comment_ids.extend(_find_comment_ids(obj))
            except Exception:
                pass
        return comment_ids

    def _update_post_metrics(self, url: str, html: str) -> None:
        """Extract reaction/comment counts and feedback_id from HTML and update DB."""
        reaction_count = None
        comment_count = None
        feedback_id = None

        m = re.search(r'"reaction_count":\s*\{\s*"count":\s*(\d+)', html)
        if m:
            reaction_count = int(m.group(1))

        m = re.search(
            r'"comment_rendering_instance":\s*\{\s*"comments":\s*\{\s*"total_count":\s*(\d+)', html
        )
        if not m:
            m = re.search(r'"total_comment_count":\s*(\d+)', html)
        if m:
            comment_count = int(m.group(1))

        m = re.search(r'"feedback"\s*:\s*\{\s*"id"\s*:\s*"([^"]+)"', html)
        if not m:
            m = re.search(r'"feedback_id"\s*:\s*"([^"]+)"', html)
        if m:
            feedback_id = m.group(1)

        if reaction_count is None and comment_count is None:
            logger.warning(f"[Crawler] No metrics found for {url}, but marking as active")
            
        logger.info(f"[Crawler] Metrics for {url}: {reaction_count} reactions, {comment_count} comments, feedback_id: {feedback_id}")
        try:
            with shared_pool.cursor() as cur:
                updates, params = [], []
                if reaction_count is not None:
                    updates.append("reaction_count = %s")
                    params.append(reaction_count)
                if comment_count is not None:
                    updates.append("comment_count = %s")
                    params.append(comment_count)
                if feedback_id is not None:
                    updates.append("feedback_id = %s")
                    params.append(feedback_id)
                
                # Always mark as active if we reached this point
                updates.append("is_active = TRUE")
                params.append(url)
                
                cur.execute(
                    f"UPDATE facebook.posts SET {', '.join(updates)} WHERE permalink_url = %s",
                    params,
                )
        except Exception as e:
            logger.error(f"[Crawler] DB update failed for {url}: {e}")

    # ═══════════════════════════════════════════════════════════════════
    #  Comment crawling for a single post
    # ═══════════════════════════════════════════════════════════════════

    async def crawl_comments_for_post(
        self,
        post_id: str,
        feedback_id: str,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
    ) -> dict:
        """Facade: Enqueues a CrawlCommentCommand to the API worker."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._api_worker_loop())
            
        progress = {
            "status": "queued",
            "total": 0,
            "message": "Đang chờ tới lượt...",
            "post_id": post_id,
        }
        self._comment_progress[post_id] = progress
        
        cmd = CrawlCommentCommand(self, post_id, feedback_id, template, client_cookie)
        await self._command_queue.put(cmd)
        return progress

    async def _execute_crawl_comments(
        self,
        post_id: str,
        feedback_id: str,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
    ) -> dict:
        """Crawl comments for a single post.

        Strategy:
        1. If comment GraphQL template exists → use it (faster, paginated).
        2. Otherwise → fetch the post page directly and extract embedded comments.

        Returns a progress dict updated in-place:
            {"status": "running"|"done"|"error", "total": int, "message": str}
        """
        progress = {
            "status": "running",
            "total": 0,
            "message": "Đang khởi tạo...",
            "post_id": post_id,
        }
        self._comment_progress[post_id] = progress

        try:
            tokens = template or await get_saved_tokens()
            if not tokens:
                progress.update(status="error", message="Không tìm thấy template.")
                return progress

            _, comment_tpl, reply_tpl = extract_templates(tokens)

            # Validate comment template: Depth2/Depth3 pagination templates are 
            # reply-pagination templates, NOT top-level comment templates. Demote 
            # them to reply_tpl and fall back to HTML scraping for top-level comments.
            if comment_tpl:
                friendly = comment_tpl.get("form_data", {}).get("fb_api_req_friendly_name", "")
                friendly_lower = friendly.lower()
                is_reply_pagination = "pagination" in friendly_lower
                if is_reply_pagination:
                    logger.warning(
                        f"[Crawler] Comment template '{friendly}' is a pagination "
                        f"template. Falling back to HTML scraping for first page."
                    )
                    if not reply_tpl:
                        reply_tpl = comment_tpl
                    comment_tpl = None

            # ── Strategy 1: GraphQL template (if captured) ───────────
            if comment_tpl:
                raw_cookie = await self._resolve_cookie(client_cookie, tokens)
                
                if not raw_cookie:
                    progress.update(status="error", message="Không tìm thấy cookie.")
                    return progress

                # Override template cookies with fresh cookie
                if "headers" in comment_tpl:
                    comment_tpl["headers"]["cookie"] = raw_cookie
                if reply_tpl and "headers" in reply_tpl:
                    reply_tpl["headers"]["cookie"] = raw_cookie

                progress["message"] = "Đang lấy comments (GraphQL)..."

                c_ids, c_text = await self._fetch_comments(feedback_id, comment_tpl)
                if c_text:
                    variables = {}
                    _, c_count, _ = extract_from_responses(
                        [c_text], variables, group_id=None, post_id=post_id
                    )
                    progress["total"] += c_count
                    progress["message"] = f"Đã lấy {progress['total']} comments"

                # Fetch replies for each comment
                if reply_tpl and c_ids:
                    for i, cid in enumerate(c_ids):
                        await asyncio.sleep(comment_delay(self.delay_config))
                        r_text = await self._fetch_replies(cid, reply_tpl)
                        if r_text:
                            _, r_count, _ = extract_from_responses(
                                [r_text], {}, group_id=None, post_id=post_id
                            )
                            progress["total"] += r_count
                            progress["message"] = (
                                f"Đã lấy {progress['total']} comments "
                                f"(replies {i+1}/{len(c_ids)})"
                            )

            # ── Strategy 2: HTML page scraping (fallback) ────────────
            else:
                progress["message"] = "Đang lấy comments từ trang bài viết..."
                total = await self._scrape_comments_from_page(
                    post_id, feedback_id, tokens, client_cookie, progress,
                )
                progress["total"] = total

            progress["status"] = "done"
            progress["message"] = f"Hoàn tất! Tổng: {progress['total']} comments/replies"

        except Exception as e:
            logger.error(f"[Crawler] Comment crawl failed for {post_id}: {e}")
            progress["status"] = "error"
            progress["message"] = f"Lỗi: {e}"

        return progress

    async def _scrape_comments_from_page(
        self,
        post_id: str,
        feedback_id: str,
        tokens: dict,
        client_cookie: Optional[str],
        progress: dict,
    ) -> int:
        """Scrape comments by fetching the post page directly.

        Facebook embeds comment data as JSON in the page HTML.
        Returns the number of comments extracted.
        """
        # Resolve URL from DB
        permalink = None
        try:
            with shared_pool.cursor() as cur:
                cur.execute(
                    "SELECT permalink_url FROM facebook.posts WHERE post_id = %s",
                    (post_id,),
                )
                row = cur.fetchone()
                if row:
                    permalink = row[0]
        except Exception as e:
            logger.error(f"[Crawler] DB lookup for {post_id}: {e}")

        if not permalink:
            logger.error(f"[Crawler] No permalink found for {post_id}")
            return 0

        # Get cookies
        from proxify.platforms.facebook.token_store import parse_cookie_string
        tokens = tokens or await get_saved_tokens() or {}
        raw_cookie = await self._resolve_cookie(client_cookie, tokens)
        
        user_agent = ""
        if tokens and "headers" in tokens:
            user_agent = tokens["headers"].get("user-agent", "")
            
        cookies = parse_cookie_string(raw_cookie) if raw_cookie else None
                
        if not user_agent:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        if not cookies:
            logger.error("[Crawler] No cookies for page scrape")
            return 0

        progress["message"] = f"Đang tải trang {permalink[:50]}..."

        try:
            resp = await self._safe_request(
                "GET", permalink,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "vi,en;q=0.9",
                    "User-Agent": user_agent,
                },
                cookies=cookies,
                allow_redirects=True,
                timeout=20.0,
            )

            if resp.is_blocked:
                logger.warning(f"[Crawler] Blocked fetching {permalink}")
                return 0

            html = resp.text
            
            # Check if post is deleted/unavailable
            if "B\\u1ea1n hi\\u1ec7n kh\\u00f4ng xem \\u0111\\u01b0\\u1ee3c n\\u1ed9i dung n\\u00e0y" in html:
                logger.info(f"[Crawler] Post {permalink} is INACTIVE (Error page detected) during comment crawl")
                try:
                    with shared_pool.cursor() as cur:
                        cur.execute("UPDATE facebook.posts SET is_active = FALSE WHERE permalink_url = %s", (permalink,))
                except Exception as e:
                    logger.error(f"[Crawler] DB update failed for inactive {permalink}: {e}")
                return 0

            progress["message"] = "Đang phân tích dữ liệu..."

            # Extract embedded JSON data blocks (Facebook embeds data as JSON)
            count = 0
            responses = []

            # Facebook embeds data in multiple formats - try all
            # 1. Standard requires/define blocks
            for block_start in ['{"require":', '{"__dr":']:
                idx = 0
                while True:
                    pos = html.find(block_start, idx)
                    if pos == -1:
                        break
                    # Find matching end brace
                    depth = 0
                    end = pos
                    for ci in range(pos, min(pos + 500000, len(html))):
                        if html[ci] == '{':
                            depth += 1
                        elif html[ci] == '}':
                            depth -= 1
                            if depth == 0:
                                end = ci + 1
                                break
                    if end > pos:
                        responses.append(html[pos:end])
                    idx = end if end > pos else pos + 1

            if responses:
                logger.info(f"[Crawler] Found {len(responses)} embedded data blocks")
                # Use extract_from_responses to parse and upsert
                _, c_count, _ = extract_from_responses(
                    responses, {}, group_id=None, post_id=post_id
                )
                count += c_count
                progress["message"] = f"Đã lấy {count} comments từ trang"
            else:
                logger.warning(f"[Crawler] No embedded data found in {permalink}")

            return count

        except StealthRequestError as e:
            logger.error(f"[Crawler] Page scrape failed for {permalink}: {e}")
            return 0


# ── Recursive comment ID finder (pure function) ───────────────────────


def _find_comment_ids(obj) -> list[str]:
    """Recursively find comment IDs in a parsed JSON object."""
    ids: list[str] = []
    if isinstance(obj, dict):
        if "comment_id" in obj and isinstance(obj["comment_id"], str):
            ids.append(obj["comment_id"])
        elif (
            "id" in obj
            and isinstance(obj["id"], str)
            and len(obj["id"]) > 10
            and obj.get("__typename") == "Comment"
        ):
            ids.append(obj["id"])
        for v in obj.values():
            ids.extend(_find_comment_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            ids.extend(_find_comment_ids(v))
    return ids


# ═══════════════════════════════════════════════════════════════════════
#  Backward-compatible module-level aliases
# ═══════════════════════════════════════════════════════════════════════
#
# These allow existing code to keep using:
#   from proxify.platforms.facebook.crawler import start_crawler, group_crawl_state
#
# without modification.

_default_crawler = FacebookCrawler()

# Mutable state references (shared with plugins)
group_crawl_state = _default_crawler.crawl_state
refresh_progress = _default_crawler.refresh_progress

# Legacy _crawler_manager reference (used by dashboard.py)
_crawler_manager = _default_crawler.manager


async def start_crawler(
    group_id: str,
    start_timestamp: int,
    end_timestamp: int,
    template: Optional[dict] = None,
    client_cookie: Optional[str] = None,
    reset_cursor: bool = True,
) -> None:
    """Module-level alias for ``FacebookCrawler.crawl_group_feed``."""
    await _default_crawler.crawl_group_feed(
        group_id, start_timestamp, end_timestamp, template, client_cookie, reset_cursor
    )


async def crawl_specific_posts(urls: list[str]) -> dict:
    """Module-level alias for ``FacebookCrawler.crawl_specific_posts``."""
    return await _default_crawler.crawl_specific_posts(urls)


async def crawl_post_comments(
    post_id: str, feedback_id: str, client_cookie: Optional[str] = None,
) -> dict:
    """Module-level alias for ``FacebookCrawler.crawl_comments_for_post``."""
    return await _default_crawler.crawl_comments_for_post(
        post_id, feedback_id, client_cookie=client_cookie,
    )


def get_comment_progress(post_id: str) -> Optional[dict]:
    """Get the current comment crawl progress for a post."""
    return _default_crawler._comment_progress.get(post_id)

