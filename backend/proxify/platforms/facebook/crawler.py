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
from proxify.platforms.facebook.stealth import (
    CrawlDelayConfig,
    page_delay,
    comment_delay,
    SessionStateManager,
    GlobalNetworkClient,
)
from proxify.platforms.facebook.auth import get_saved_tokens, extract_templates
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper
from proxify.platforms.facebook.workflow import (
    state_observer,
    CrawlFeedCommand,
    RefreshCommand,
    CrawlCommentCommand,
)

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
    
    # 1. Ưu tiên giải mã qua Extension Bridge (An toàn tuyệt đối, thực thi trong Chrome thật)
    try:
        from proxify.platforms.facebook.bridge import bridge
        if bridge.is_connected(threshold=60.0):
            res = await bridge.execute_request(url=url, method="GET", timeout=12)
            text = res.get("text", "")
            if text:
                match = re.search(r'"groupID":"(\d+)"', text)
                if not match:
                    match = re.search(r'(?:groupID|group_id|targetID)["\'\\]*:\s*["\'\\]*(\d+)', text)
                if match:
                    numeric_id = match.group(1)
                    logger.info(f"[Crawler] Resolved slug '{group_id_or_slug}' -> Numeric ID '{numeric_id}' via Extension Bridge")
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
        logger.warning(f"[Crawler] Lỗi phân giải slug qua Extension Bridge: {e}")

    # 2. Fallback: Nếu không có bridge, thử curl_cffi KHÔNG mang cookie nhạy cảm (tránh checkpoint)
    try:
        from curl_cffi.requests import AsyncSession
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "vi,en;q=0.9",
        }
        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(url, headers=headers, timeout=10)
            text = resp.text
            if text:
                match = re.search(r'"groupID":"(\d+)"', text)
                if not match:
                    match = re.search(r'(?:groupID|group_id|targetID)["\'\\]*:\s*["\'\\]*(\d+)', text)
                if match:
                    numeric_id = match.group(1)
                    logger.info(f"[Crawler] Resolved slug '{group_id_or_slug}' -> Numeric ID '{numeric_id}' via curl_cffi")
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
        logger.warning(f"[Crawler] Lỗi phân giải slug qua curl_cffi: {e}")
    
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
        
        self._stop_flag = False
        self._stopped_comment_posts: set[str] = set()
        self._feed_queue = asyncio.Queue()
        self._comment_queue = asyncio.Queue()
        self._command_queue = self._feed_queue  # Backward compatibility
        
        try:
            loop = asyncio.get_running_loop()
            self._feed_worker_task = loop.create_task(self._feed_worker_loop())
            self._comment_worker_task = loop.create_task(self._comment_worker_loop())
            self._worker_task = self._feed_worker_task
        except RuntimeError:
            self._feed_worker_task = None
            self._comment_worker_task = None
            self._worker_task = None

    @property
    def manager(self) -> StealthSessionManager:
        return self.network_client.manager

    async def _feed_worker_loop(self):
        """Worker for batch group feed crawls and post metric refreshes."""
        while True:
            command = await self._feed_queue.get()
            try:
                await command.execute()
            except Exception as e:
                logger.error(f"[Feed Worker] Command failed: {e}")
            finally:
                self._feed_queue.task_done()

    async def _comment_worker_loop(self):
        """Dedicated worker for on-demand comment crawling.
        Runs concurrently with feed crawl to guarantee ZERO Head-of-Line blocking!
        """
        while True:
            command = await self._comment_queue.get()
            try:
                await command.execute()
            except Exception as e:
                logger.error(f"[Comment Worker] Command failed: {e}")
            finally:
                self._comment_queue.task_done()

    # Alias for backward compatibility
    _api_worker_loop = _feed_worker_loop

    async def _safe_request(self, method: str, url: str, **kwargs):
        """Wrapper that executes request with dual-engine strategy:
        1. Extension Bridge (executes First-Party inside the user's active Facebook tab)
        2. Fallback to native curl_cffi (via GlobalNetworkClient / StealthSessionManager)
        """
        from proxify.platforms.facebook.bridge import bridge
        
        headers = kwargs.get("headers", {})
        data = kwargs.get("data")
        raw_data = data
        if isinstance(data, bytes):
            data_str = data.decode("utf-8", "ignore")
        else:
            data_str = data or ""
            
        import time
        result = None
        is_comment = kwargs.get("is_comment_crawl", False)
        bridge_timeout = 8 if is_comment else 65
        max_retries = 1 if is_comment else 2
        
        for attempt in range(max_retries):
            use_bridge = bridge.is_connected(threshold=60.0)
            logger.debug(f"[Crawler] Bridge connection check: is_connected={use_bridge} (attempt {attempt+1}/{max_retries}, last poll: {time.time() - bridge.last_poll_time:.1f}s ago, is_comment={is_comment})")
            
            if use_bridge:
                try:
                    result = await bridge.execute_request(
                        url=url, 
                        method=method, 
                        headers=headers, 
                        data=data_str,
                        timeout=bridge_timeout
                    )
                    if result:
                        logger.debug(
                            f"[Crawler] Bridge returned status={result.get('status_code')}, "
                            f"len={len(result.get('text', ''))}, "
                            f"in_tab={result.get('executed_in_tab')}, "
                            f"tab_url={result.get('tab_url')}, "
                            f"tab_err={result.get('tab_error')}"
                        )
                        if result.get("status_code") == 200 and result.get("status") != "error":
                            break
                except Exception as e:
                    logger.warning(f"[Crawler] Bridge request exception (attempt {attempt+1}): {e}")

            # If attempt failed but extension is still actively polling, retry before aborting
            if attempt < max_retries - 1 and bridge.is_connected(threshold=30.0):
                logger.info(f"[Crawler] Bridge attempt {attempt+1} did not return 200. Retrying in 2s...")
                await asyncio.sleep(2)
                continue
            else:
                break

        # If Extension Bridge is offline, disconnected, or returns error 1357001, handle appropriately
        bridge_failed = False
        if not result or result.get("status") == "error" or "1357001" in result.get("text", ""):
            bridge_failed = True

        if bridge_failed:
            # For GET requests (e.g. HTML page scraping for comments) or comment crawls,
            # safely execute via native curl_cffi with Chrome120 fingerprint impersonation.
            if method.upper() == "GET" or is_comment:
                logger.info(f"[Crawler] Bridge unavailable/failed for {method} {url[:60]}, using native curl_cffi fallback...")
                data_to_send = data_str.encode("utf-8") if isinstance(data_str, str) else raw_data
                try:
                    resp = await self.network_client.safe_request(
                        method=method,
                        url=url,
                        headers=headers,
                        data=data_to_send,
                        cookies=kwargs.get("cookies"),
                        allow_redirects=kwargs.get("allow_redirects", False),
                    )
                    class MockResponse:
                        def __init__(self, r):
                            self.text = r.text if r else ""
                            self.status_code = r.status_code if r else 500
                            self.is_blocked = r.is_blocked if r else True
                    return MockResponse(resp)
                except Exception as e:
                    logger.error(f"[Crawler] curl_cffi fallback failed: {e}")
                    class MockResponse:
                        def __init__(self):
                            self.text = ""
                            self.status_code = 500
                            self.is_blocked = True
                    return MockResponse()

            err_detail = result.get("tab_error") if result else None
            if not use_bridge:
                disconnect_reason = "Chrome Extension chưa kết nối hoặc đã bị tắt"
            elif err_detail:
                disconnect_reason = f"Lỗi phản hồi Extension: {err_detail}"
            else:
                disconnect_reason = "Không nhận được phản hồi từ Chrome Extension"

            logger.warning(f"[Crawler] {disconnect_reason}. Dừng cào an toàn để bảo vệ tài khoản Facebook tránh bị Logout.")
            self._stop_flag = True
            self.crawl_state.update(
                status="error",
                message=(
                    f"⚠️ {disconnect_reason}!\n\n"
                    "🛡️ Để bảo vệ an toàn tài khoản tránh bị Facebook tự động Logout,\n"
                    "hệ thống đã tạm dừng cào thay vì gửi request từ Docker.\n\n"
                    "👉 Vui lòng mở Chrome có tab Facebook và Extension Proxify đang hoạt động rồi bấm cào lại!"
                ),
                toast_message="Mất kết nối Chrome Extension! Đã tạm dừng cào để bảo vệ tài khoản.",
                toast_icon="⚠️",
                updated_at=time.time(),
            )
            class MockResponse:
                def __init__(self):
                    self.text = ""
                    self.status_code = 503
                    self.is_blocked = True
                    self.is_disconnected = True
            return MockResponse()

        class MockResponse:
            def __init__(self, data: dict):
                self.text = data.get("text", "")
                self.status_code = data.get("status_code", 200)
                self.is_blocked = False
                
        return MockResponse(result)

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
        self._stop_flag = False
        if self._feed_worker_task is None or self._feed_worker_task.done():
            self._feed_worker_task = asyncio.create_task(self._feed_worker_loop())
        cmd = CrawlFeedCommand(self, group_id, start_timestamp, end_timestamp, template, client_cookie, reset_cursor)
        await self._feed_queue.put(cmd)

    def stop_crawling(self) -> None:
        """Signal the crawler to stop the current loop."""
        self._stop_flag = True
        logger.info("[Crawler] Receive STOP signal.")
        self.crawl_state.update(
            status="idle",
            message="⛔ Đã dừng quá trình thu thập dữ liệu.",
            toast_message=None,
            toast_icon=None,
            updated_at=time.time(),
        )

    def stop_comment_crawling(self, post_id: Optional[str] = None) -> None:
        """Signal the crawler to stop comment crawling for a specific post or all posts."""
        if post_id:
            pid = str(post_id)
            self._stopped_comment_posts.add(pid)
            if pid in self._comment_progress:
                self._comment_progress[pid]["status"] = "idle"
                self._comment_progress[pid]["message"] = "Đã dừng thu thập bình luận."
            logger.info(f"[Crawler] Stop signal recorded for comment crawl: {pid}")
        else:
            for pid in list(self._comment_progress.keys()):
                self._stopped_comment_posts.add(str(pid))
                self._comment_progress[str(pid)]["status"] = "idle"
                self._comment_progress[str(pid)]["message"] = "Đã dừng thu thập bình luận."
            logger.info("[Crawler] Stop signal recorded for ALL comment crawls.")

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
            self.crawl_state.update(
                status="error",
                message=(
                    "❌ Extension chưa bắt được gói tin GraphQL thực.\n\n"
                    "⚠️ Hướng dẫn khắc phục:\n"
                    "1. Vui lòng mở Facebook trong trình duyệt.\n"
                    "2. Truy cập vào MỘT NHÓM FACEBOOK BẤT KỲ.\n"
                    "3. Cuộn chuột lướt xuống vài bài viết để Extension tự động bắt gói dữ liệu.\n"
                    "4. Sau đó quay lại đây và bấm 'Bắt đầu thu thập' một lần nữa!"
                )
            )
            return

        feed_tpl, comment_tpl, reply_tpl = extract_templates(tokens)
        if not feed_tpl or "form_data" not in feed_tpl:
            logger.error("No FB Feed template found. Browse a Facebook Group through Proxify first.")
            self.crawl_state.update(
                status="error",
                message=(
                    "❌ Extension chưa bắt được gói tin GraphQL thực.\n\n"
                    "⚠️ Hướng dẫn khắc phục:\n"
                    "1. Vui lòng mở Facebook trong trình duyệt.\n"
                    "2. Truy cập vào MỘT NHÓM FACEBOOK BẤT KỲ.\n"
                    "3. Cuộn chuột lướt xuống vài bài viết để Extension tự động bắt gói dữ liệu.\n"
                    "4. Sau đó quay lại đây và bấm 'Bắt đầu thu thập' một lần nữa!"
                )
            )
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

        # ── Kiểm tra kết nối Extension Bridge trước khi chạy cào ───────────
        from proxify.platforms.facebook.bridge import bridge
        if not bridge.is_connected(threshold=60.0):
            logger.warning("[Crawler] Chrome Extension is offline before crawl start. Aborting to avoid logout.")
            self.crawl_state.update(
                status="error",
                message=(
                    "⚠️ Chrome Extension chưa kết nối hoặc chưa mở tab Facebook!\n\n"
                    "🛡️ Để đảm bảo an toàn tuyệt đối (tránh bị Facebook tự động Logout),\n"
                    "hệ thống yêu cầu chạy In-Tab qua Extension.\n\n"
                    "👉 Vui lòng mở Chrome có cài Proxify Extension, mở sẵn tab Facebook và thử lại!"
                ),
                toast_message="Mất kết nối Chrome Extension! Vui lòng mở Chrome.",
                toast_icon="⚠️",
                updated_at=time.time(),
            )
            return

        # ── Prepare headers & state ─────────────────────────────────
        self.crawl_state.update(
            status="running",
            group_id=group_id,
            message=f"[SUCCESS] Tiến trình đang chạy ngầm cho Group ID: {group_id}...\nDữ liệu sẽ tự động xuất hiện bên dưới.",
        )

        headers = self._build_headers(feed_tpl, raw_cookie, numeric_group_id)
        form_data_template = feed_tpl.get("form_data", {}).copy()
        
        # INJECT FRESH TOKENS from Extension ONLY if missing from template
        # (Template tokens are already cryptographically coherent, do not overwrite them!)
        from proxify.platforms.facebook.api import IN_MEMORY_COOKIES
        fresh_fb_dtsg = IN_MEMORY_COOKIES.get("fb_dtsg")
        fresh_lsd = IN_MEMORY_COOKIES.get("lsd")
        if fresh_fb_dtsg and not form_data_template.get("fb_dtsg"):
            form_data_template["fb_dtsg"] = fresh_fb_dtsg
            form_data_template["jazoest"] = "2" + str(sum(ord(c) for c in fresh_fb_dtsg))
        if fresh_lsd and not form_data_template.get("lsd"):
            form_data_template["lsd"] = fresh_lsd
            
        import re
        c_user_match = re.search(r'c_user=([^;]+)', raw_cookie)
        if c_user_match and not form_data_template.get("__user"):
            form_data_template["__user"] = c_user_match.group(1)
        elif IN_MEMORY_COOKIES.get("user_id") and not form_data_template.get("__user"):
            form_data_template["__user"] = IN_MEMORY_COOKIES["user_id"]
            
        fresh_sd = IN_MEMORY_COOKIES.get("sd")
        if fresh_sd and isinstance(fresh_sd, dict):
            if fresh_sd.get("hs"):
                form_data_template["__hs"] = fresh_sd["hs"]
            if fresh_sd.get("rev"):
                form_data_template["__rev"] = fresh_sd["rev"]
            if fresh_sd.get("hsi"):
                form_data_template["__hsi"] = fresh_sd["hsi"]
            if fresh_sd.get("spin_r"):
                form_data_template["__spin_r"] = fresh_sd["spin_r"]
            if fresh_sd.get("spin_b"):
                form_data_template["__spin_b"] = fresh_sd["spin_b"]
            if fresh_sd.get("spin_t"):
                form_data_template["__spin_t"] = fresh_sd["spin_t"]
            
        session_state = SessionStateManager()

        # ── Pagination loop ─────────────────────────────────────────
        from proxify.platforms.facebook.database import fb_db
        cursor = "" if reset_cursor else (fb_db.config.get(f"crawl_cursor_{group_id}") or "")
        consecutive_old_pages = 0

        for page_num in range(MAX_PAGES_PER_SESSION):
            if self._stop_flag:
                logger.info("[Crawler] Stop flag detected. Breaking feed loop.")
                break

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
                            logger.error(f"[Crawler] Full error response: {stripped_resp[:2000]}")
                            error_desc = json_data.get("errorDescription", "")
                            if error_code == 1357001:
                                if error_desc and "thành viên" in error_desc:
                                    msg = f"❌ {error_summary}.\n{error_desc}"
                                else:
                                    msg = "❌ Cookie đã hết hạn hoặc bị lỗi xác thực (Error 1357001).\nVui lòng cập nhật lại cookie mới."
                                self.crawl_state.update(
                                    status="error",
                                    message=msg,
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

                # Check for Extension disconnection or stop flag
                if getattr(resp, "is_disconnected", False) or self._stop_flag:
                    logger.warning("[Crawler] Disconnected from Extension Bridge or stop flag set. Halting crawl loop immediately.")
                    break

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

                # Note: Feed responses (GroupsCometFeedRegularStoriesPaginationQuery) already embed
                # top comments and reactions in each Story node. Deep comment crawling is handled
                # on-demand via the dedicated Comment Worker to keep feed crawling fast (~1.5s/page).

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
        if self.crawl_state.get("status") == "running":
            self.crawl_state.update({
                "status": "idle",
                "message": f"Hoàn tất thu thập cho Group ID: {group_id}",
            })

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
        from proxify.platforms.facebook.auth import parse_cookie_string
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
        """Resolve cookie string from available sources (priority chain)."""
        tpl_cookie = ""
        if tokens:
            for key in ["feed", "comment", "reply"]:
                if key in tokens and isinstance(tokens[key], dict) and "headers" in tokens[key]:
                    cookie_val = tokens[key]["headers"].get("cookie") or tokens[key]["headers"].get("Cookie")
                    if cookie_val:
                        tpl_cookie = cookie_val.strip()
                        break
        
        # If the template cookie is missing 'xs' (due to Chrome Extension API hiding HttpOnly/Partitioned cookies),
        # but we have a valid client_cookie with 'xs', we MUST merge 'xs' into the template cookie!
        if tpl_cookie and "xs=" not in tpl_cookie and client_cookie and "xs=" in client_cookie:
            logger.warning("[Crawler] Template cookie lacks 'xs'. Merging 'xs' from fallback cookie!")
            import re
            xs_match = re.search(r'xs=([^;]+)', client_cookie)
            if xs_match:
                tpl_cookie = f"{tpl_cookie}; xs={xs_match.group(1)}"
                
        if tpl_cookie and "xs=" in tpl_cookie:
            logger.debug("[Crawler] Using exact matching cookie from template (with xs)")
            return tpl_cookie

        # Highest priority: user provided cookie
        if client_cookie and ("c_user=" in client_cookie or "xs=" in client_cookie):
            logger.debug("[Crawler] Using user-provided fallback cookie")
            return client_cookie.strip()

        if client_cookie:
            logger.debug("[Crawler] Using user-provided cookie")
            return client_cookie.strip()

        if tpl_cookie:
            logger.debug("[Crawler] Using template cookie")
            return tpl_cookie

        try:
            from proxify.platforms.facebook.auth import IN_MEMORY_COOKIES
            mem_cookie = IN_MEMORY_COOKIES.get("cookie", "")
            if mem_cookie:
                logger.debug("[Crawler] Using IN_MEMORY_COOKIES fallback")
                return mem_cookie.strip()
        except Exception:
            pass

        # Fallback to persistent DB config
        try:
            from proxify.platforms.facebook.database import fb_db
            db_cookie = fb_db.config.get("fb_cookie")
            if db_cookie and db_cookie != "[REDACTED]":
                logger.debug("[Crawler] Using persistent fb_cookie from config DB")
                return db_cookie.strip()
        except Exception as e:
            logger.debug(f"[Crawler] Error fetching cookie from config DB: {e}")

        # Fallback to requests table for the most recent Facebook cookie (if unredacted)
        try:
            with shared_pool.cursor() as cur:
                cur.execute("""
                    SELECT request_headers::jsonb->>'Cookie'
                    FROM requests
                    WHERE url LIKE '%facebook.com%' AND request_headers::jsonb->>'Cookie' IS NOT NULL
                      AND request_headers::jsonb->>'Cookie' != '[REDACTED]'
                    ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                if row and row[0] and row[0] != "[REDACTED]":
                    logger.debug("[Crawler] Using latest intercepted Facebook cookie from requests table")
                    return row[0].strip()
        except Exception as e:
            logger.debug(f"[Crawler] Error fetching cookie from requests table: {e}")

        logger.error("[Crawler] No cookies found!")
        return ""

    @staticmethod
    def _build_headers(feed_tpl: dict, cookie: str, group_id: str) -> dict:
        """Build request headers from template, fixing anti-detection issues."""
        headers = feed_tpl.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["cookie"] = cookie
        headers["referer"] = f"https://www.facebook.com/groups/{group_id}"
        
        # We are using impersonate=None in StealthSessionManager so we MUST keep the browser's User-Agent
        return headers

    @staticmethod
    def _set_variables(data: dict, group_id: str, cursor: str) -> Optional[str]:
        """Set GraphQL variables in form data. Returns cursor or None on error."""
        try:
            variables = json.loads(data.get("variables", "{}"))
            
            # Bắt buộc sắp xếp theo thời gian đăng bài (CHRONOLOGICAL)
            # Tuyệt đối không giữ TOP_POSTS hay RECENT_ACTIVITY của template vì sẽ làm ngày bài viết bị nhảy lộn xộn
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
                    c_times = DataHelper.find_key(rp, "creation_time")
                    if not c_times:
                        c_times = DataHelper.find_key(rp, "created_time")
                    
                    t = c_times[0] if c_times else None
                    if t:
                        try:
                            timestamps.append(int(t))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        if not timestamps:
            return False, consecutive, []

        if not start_ts:
            return False, 0, timestamps

        # If ALL posts on this page are older than start_ts, increment consecutive counter.
        # We require at least 3 consecutive pages of old posts to stop.
        # This prevents stopping prematurely if the first few pages contain many Pinned Posts
        # that are very old, guaranteeing we've reached the actual timeline.
        if all(t < start_ts for t in timestamps):
            consecutive += 1
            logger.info(f"[Crawler] Old posts detected ({len(timestamps)} posts older than {start_ts}). Consecutive old pages: {consecutive}/3")
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
                res = await self._fetch_comments(fid, comment_tpl)
                c_ids, c_text = res[0], res[1]
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

    @staticmethod
    def _extract_comment_page_info(resp_text: str, current_direction: str = "after") -> tuple[Optional[str], bool, str]:
        """Extract cursor, has_more, and direction ('after' or 'before') for comment pagination."""
        try:
            for line in resp_text.split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                nodes = DataHelper.extract_nodes(data, "Feedback")
                for fb in nodes:
                    comments_obj = fb.get("comment_rendering_instance_for_feed_location", {}).get("comments") or fb.get("comments")
                    if isinstance(comments_obj, dict) and "page_info" in comments_obj:
                        pi = comments_obj["page_info"]
                        # Once traversing in a direction, STAY in that direction to prevent ping-pong loops
                        if current_direction == "after":
                            if pi.get("has_next_page") and pi.get("end_cursor"):
                                return pi.get("end_cursor"), True, "after"
                            return None, False, "after"
                        elif current_direction == "before":
                            if pi.get("has_previous_page") and pi.get("start_cursor"):
                                return pi.get("start_cursor"), True, "before"
                            return None, False, "before"
                        else:
                            # Initial probe
                            if pi.get("has_next_page") and pi.get("end_cursor"):
                                return pi.get("end_cursor"), True, "after"
                            elif pi.get("has_previous_page") and pi.get("start_cursor"):
                                return pi.get("start_cursor"), True, "before"
        except Exception:
            pass
        return None, False, ""

    async def _fetch_comments(
        self, feedback_id: str, template: dict, cursor: Optional[str] = None, direction: str = "after"
    ) -> tuple[list[str], str, Optional[str], bool, str]:
        """Fetch comment IDs for a post feedback_id with bi-directional cursor support."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-FB-Friendly-Name"] = "CommentsListComponentsPaginationQuery"
        data = template.get("form_data", {}).copy()

        # Format feedback_id: Facebook Comet expects base64 "ZmVlZGJhY2s6..."
        target_fbid = feedback_id
        if not target_fbid.startswith("ZmVlZ") and ":" not in target_fbid:
            try:
                import base64
                target_fbid = base64.b64encode(f"feedback:{feedback_id}".encode()).decode()
            except Exception:
                pass

        try:
            variables = json.loads(data.get("variables", "{}"))
            variables["id"] = target_fbid
            if "comments_target_id" in variables:
                variables["comments_target_id"] = target_fbid
            if "feedback_id" in variables:
                variables["feedback_id"] = target_fbid
            
            # Force unfiltered mode (Tất cả bình luận) so Facebook returns ALL comments
            # instead of hiding comments under 'Most relevant' (Phù hợp nhất)
            variables["commentsIntentToken"] = "CHRONOLOGICAL_UNFILTERED_INTENT_V1"
            
            # Cursor pagination (bi-directional: after or before)
            if cursor:
                if direction == "before":
                    variables["commentsBeforeCursor"] = cursor
                    variables["commentsBeforeCount"] = -1
                    variables["commentsAfterCursor"] = None
                    variables["commentsAfterCount"] = None
                else:
                    variables["commentsAfterCursor"] = cursor
                    variables["commentsAfterCount"] = -1
                    variables["commentsBeforeCursor"] = None
                    variables["commentsBeforeCount"] = None
            else:
                variables["commentsAfterCursor"] = None
                variables["commentsAfterCount"] = -1
                variables["commentsBeforeCursor"] = None
                variables["commentsBeforeCount"] = None
                
            data["variables"] = json.dumps(variables, separators=(",", ":"))
        except Exception as e:
            logger.warning(f"[Crawler] Error updating comment variables: {e}")

        try:
            resp = await self._safe_request(
                "POST", GRAPHQL_ENDPOINT,
                headers=headers,
                data=urllib.parse.urlencode(data).encode(),
                is_comment_crawl=True,
            )
            comment_ids = self._parse_comment_ids(resp.text)
            next_cursor, has_more, next_dir = self._extract_comment_page_info(resp.text, current_direction=direction)
            return comment_ids, resp.text, next_cursor, has_more, next_dir
        except StealthRequestError as e:
            logger.error(f"[Crawler] Comment fetch failed for {feedback_id}: {e}")
            return [], "", None, False, ""

    async def _fetch_replies(self, comment_id: str, template: dict) -> str:
        """Fetch replies for a comment."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-FB-Friendly-Name"] = "Depth1CommentsListPaginationQuery"
        data = template.get("form_data", {}).copy()

        try:
            variables = json.loads(data.get("variables", "{}"))
            variables["comment_id"] = comment_id
            variables["id"] = comment_id
            
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
                is_comment_crawl=True,
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
        """Facade: Enqueues a CrawlCommentCommand to the dedicated comment worker."""
        if self._comment_worker_task is None or self._comment_worker_task.done():
            self._comment_worker_task = asyncio.create_task(self._comment_worker_loop())
            
        progress = {
            "status": "queued",
            "total": 0,
            "message": "Đang chờ tới lượt...",
            "post_id": post_id,
        }
        self._comment_progress[post_id] = progress
        
        cmd = CrawlCommentCommand(self, post_id, feedback_id, template, client_cookie)
        await self._comment_queue.put(cmd)
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
        self._stopped_comment_posts.discard(str(post_id))

        try:
            tokens = template or await get_saved_tokens() or {}
            _, comment_tpl, reply_tpl = extract_templates(tokens) if tokens else (None, None, None)

            # Validate comment template:
            # 1. Depth1/Depth2/Depth3 or reply templates are reply-pagination templates, NOT top-level comment templates.
            # 2. Queries like 'CometUFIConversationGuideContainerQuery' or queries NOT containing 'comment' or 'ufi' are NOT comment templates.
            if comment_tpl:
                friendly = comment_tpl.get("form_data", {}).get("fb_api_req_friendly_name", "")
                friendly_lower = friendly.lower()
                is_depth_or_reply = "depth" in friendly_lower or "reply" in friendly_lower
                is_valid_comment_query = ("comment" in friendly_lower or "ufi" in friendly_lower) and not ("guide" in friendly_lower or "suggestion" in friendly_lower)
                
                if not is_valid_comment_query:
                    logger.warning(
                        f"[Crawler] Comment template '{friendly}' is not a valid comment query."
                    )
                    comment_tpl = None
                elif is_depth_or_reply:
                    logger.warning(
                        f"[Crawler] Comment template '{friendly}' is a reply/depth pagination "
                        f"template. Demoting to reply_tpl."
                    )
                    if not reply_tpl:
                        reply_tpl = comment_tpl
                    comment_tpl = None

            # ── Synthetic template fallback if template not captured yet ──
            if not comment_tpl:
                feed_tpl = tokens.get("feed") if isinstance(tokens, dict) else None
                if not feed_tpl:
                    from proxify.platforms.facebook.auth import IN_MEMORY_TEMPLATES
                    feed_tpl = IN_MEMORY_TEMPLATES.get("feed")
                
                base_form = feed_tpl.get("form_data", {}).copy() if feed_tpl and isinstance(feed_tpl.get("form_data"), dict) else {}
                base_headers = feed_tpl.get("headers", {}).copy() if feed_tpl and isinstance(feed_tpl.get("headers"), dict) else {}
                
                # If base_form is empty, extract from the latest intercepted Facebook GraphQL request in DB
                if not base_form:
                    try:
                        with shared_pool.cursor() as cur:
                            # 1. First priority: real CommentsListComponentsPaginationQuery intercepted earlier
                            cur.execute("""
                                SELECT request_body, request_headers::jsonb
                                FROM requests
                                WHERE graphql_operation = 'CommentsListComponentsPaginationQuery'
                                  AND status_code = 200 AND length(response_body) > 1000
                                ORDER BY id DESC LIMIT 1
                            """)
                            r_row = cur.fetchone()
                            is_comment_source = bool(r_row)
                            
                            # 2. Second priority: any recent GraphQL query with fb_dtsg
                            if not r_row:
                                cur.execute("""
                                    SELECT request_body, request_headers::jsonb
                                    FROM requests
                                    WHERE url LIKE '%facebook.com/api/graphql%' AND request_body LIKE '%fb_dtsg=%'
                                    ORDER BY id DESC LIMIT 1
                                """)
                                r_row = cur.fetchone()

                            if r_row and r_row[0]:
                                parsed_body = urllib.parse.parse_qs(r_row[0])
                                for k, vals in parsed_body.items():
                                    if vals:
                                        base_form[k] = vals[0]
                                if r_row[1] and isinstance(r_row[1], dict):
                                    base_headers = r_row[1]
                                
                                # If the source was NOT a comments query, strip query-specific signature params
                                if not is_comment_source:
                                    for noisy_key in ["__dyn", "__csr", "__hsdp", "__hblp", "__sjsp"]:
                                        base_form.pop(noisy_key, None)
                                
                                logger.debug(f"[Crawler] Populated base_form from GraphQL request in DB (keys={len(base_form)}, is_comment_source={is_comment_source})")
                    except Exception as e:
                        logger.debug(f"[Crawler] Error fetching base_form from requests table: {e}")
                
                logger.debug("[Crawler] Generating synthetic CommentsListComponentsPaginationQuery template...")
                comment_form = base_form.copy()
                comment_form["fb_api_req_friendly_name"] = "CommentsListComponentsPaginationQuery"
                comment_form["doc_id"] = "27973447728944010"
                comment_form["fb_api_caller_class"] = "RelayModern"
                comment_form["server_timestamps"] = "true"
                comment_form["__comet_req"] = "15"
                comment_form["__a"] = "1"
                
                target_fbid = feedback_id
                if not target_fbid.startswith("ZmVlZ") and ":" not in target_fbid:
                    import base64
                    target_fbid = base64.b64encode(f"feedback:{feedback_id}".encode()).decode()
                    
                comment_form["variables"] = json.dumps({
                    "commentsAfterCount": -1,
                    "commentsAfterCursor": None,
                    "commentsBeforeCount": None,
                    "commentsBeforeCursor": None,
                    "commentsIntentToken": "CHRONOLOGICAL_UNFILTERED_INTENT_V1",
                    "feedLocation": "POST_PERMALINK_DIALOG",
                    "focusCommentID": None,
                    "scale": 1,
                    "targetDialect": None,
                    "useDefaultActor": False,
                    "id": target_fbid,
                    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
                    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
                    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
                    "__relay_internal__pv__IsWorkUserrelayprovider": False
                }, separators=(",", ":"))
                
                comment_headers = base_headers.copy()
                comment_headers["Content-Type"] = "application/x-www-form-urlencoded"
                comment_headers["X-FB-Friendly-Name"] = "CommentsListComponentsPaginationQuery"
                comment_tpl = {
                    "headers": comment_headers,
                    "form_data": comment_form
                }

            if not reply_tpl:
                feed_tpl = tokens.get("feed") if isinstance(tokens, dict) else None
                if not feed_tpl:
                    from proxify.platforms.facebook.auth import IN_MEMORY_TEMPLATES
                    feed_tpl = IN_MEMORY_TEMPLATES.get("feed")
                base_form = feed_tpl.get("form_data", {}).copy() if feed_tpl and isinstance(feed_tpl.get("form_data"), dict) else {}
                base_headers = feed_tpl.get("headers", {}).copy() if feed_tpl and isinstance(feed_tpl.get("headers"), dict) else {}
                
                reply_form = base_form.copy()
                reply_form["fb_api_req_friendly_name"] = "Depth1CommentsListPaginationQuery"
                reply_form["doc_id"] = "28318517357780677"
                reply_form["fb_api_caller_class"] = "RelayModern"
                reply_form["server_timestamps"] = "true"
                reply_form["__comet_req"] = "15"
                reply_form["__a"] = "1"
                reply_headers = base_headers.copy()
                reply_headers["Content-Type"] = "application/x-www-form-urlencoded"
                reply_headers["X-FB-Friendly-Name"] = "Depth1CommentsListPaginationQuery"
                reply_tpl = {
                    "headers": reply_headers,
                    "form_data": reply_form
                }

            # ── Strategy 1: GraphQL template ───────────
            if comment_tpl:
                raw_cookie = await self._resolve_cookie(client_cookie, tokens)
                from proxify.platforms.facebook.bridge import bridge
                
                if not raw_cookie and not bridge.is_connected(threshold=60.0):
                    progress.update(status="error", message="Không tìm thấy cookie.")
                    return progress

                # Override template cookies with fresh cookie if available
                if raw_cookie:
                    if "headers" in comment_tpl:
                        comment_tpl["headers"]["cookie"] = raw_cookie
                    if reply_tpl and "headers" in reply_tpl:
                        reply_tpl["headers"]["cookie"] = raw_cookie

                    # Synchronize user ID from cookie to form_data so Facebook doesn't return 'Unauthorized logged out query'
                    c_user_match = re.search(r'c_user=([^;]+)', raw_cookie)
                    if c_user_match:
                        uid = c_user_match.group(1)
                        if "form_data" in comment_tpl:
                            comment_tpl["form_data"]["__user"] = uid
                            comment_tpl["form_data"]["av"] = uid
                        if reply_tpl and "form_data" in reply_tpl:
                            reply_tpl["form_data"]["__user"] = uid
                            reply_tpl["form_data"]["av"] = uid

                progress["message"] = "Đang lấy comments (GraphQL)..."

                cursor = None
                has_more = True
                direction = "after"
                page_idx = 0
                max_pages = 500  # Up to ~5,000 comments per post (stops naturally when has_more=False)
                all_comment_ids = []
                seen_cursors = set()

                while has_more and page_idx < max_pages:
                    if str(post_id) in self._stopped_comment_posts:
                        logger.info(f"[Crawler] Stop signal detected for comment crawl {post_id}. Halting loop.")
                        break
                    page_idx += 1
                    c_ids, c_text, next_cursor, has_more, next_dir = await self._fetch_comments(
                        feedback_id, comment_tpl, cursor=cursor, direction=direction
                    )
                    if not c_text:
                        break
                    
                    variables = {}
                    extract_from_responses(
                        [c_text], variables, group_id=None, post_id=post_id
                    )
                    all_comment_ids.extend(c_ids)
                    current_count = len(set(all_comment_ids))
                    progress["total"] = current_count
                    progress["message"] = f"Đã lấy {current_count} comments (trang {page_idx})..."
                    
                    if next_cursor and has_more and next_cursor not in seen_cursors:
                        seen_cursors.add(next_cursor)
                        cursor = next_cursor
                        direction = next_dir
                        await asyncio.sleep(comment_delay(self.delay_config))
                    else:
                        break

                # Fetch deeper replies only for top comments if a valid reply template is available
                # (Notice: CommentsListComponentsPaginationQuery already embeds top replies in the GraphQL tree)
                if reply_tpl and all_comment_ids and str(post_id) not in self._stopped_comment_posts:
                    unique_cids = list(dict.fromkeys(all_comment_ids))[:5]  # Cap at max 5 top comments to avoid infinite crawl
                    for i, cid in enumerate(unique_cids):
                        if str(post_id) in self._stopped_comment_posts:
                            break
                        await asyncio.sleep(comment_delay(self.delay_config))
                        r_text = await self._fetch_replies(cid, reply_tpl)
                        if r_text:
                            extract_from_responses(
                                [r_text], {}, group_id=None, post_id=post_id
                            )

                # Only fallback to HTML scraping if GraphQL produced 0 comments across all pages
                if len(all_comment_ids) == 0 and str(post_id) not in self._stopped_comment_posts:
                    logger.info(f"[Crawler] GraphQL returned 0 comments for {post_id}. Falling back to Strategy 2 (HTML page scraping)...")
                    progress["message"] = "Đang lấy comments từ trang bài viết (Fallback)..."
                    total = await self._scrape_comments_from_page(
                        post_id, feedback_id, tokens, client_cookie, progress,
                    )
                    progress["total"] = total

            # ── Strategy 2: HTML page scraping (fallback) ────────────
            else:
                progress["message"] = "Đang lấy comments từ trang bài viết..."
                total = await self._scrape_comments_from_page(
                    post_id, feedback_id, tokens, client_cookie, progress,
                )
                progress["total"] = total

            # Query actual total comments saved in DB for this post
            try:
                with shared_pool.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM facebook.comments WHERE post_id = %s", (post_id,))
                    row = cur.fetchone()
                    if row and row[0] > 0:
                        progress["total"] = row[0]
            except Exception as e:
                logger.error(f"[Crawler] Error querying total comments for {post_id}: {e}")

            if str(post_id) in self._stopped_comment_posts:
                progress["status"] = "idle"
                progress["message"] = f"Đã dừng! Tổng: {progress.get('total', 0)} bình luận"
                self._stopped_comment_posts.discard(str(post_id))
            else:
                progress["status"] = "done"
                progress["message"] = f"Hoàn tất! Tổng: {progress['total']} bình luận"

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
        from proxify.platforms.facebook.auth import parse_cookie_string
        tokens = tokens or await get_saved_tokens() or {}
        raw_cookie = await self._resolve_cookie(client_cookie, tokens)
        
        user_agent = ""
        if tokens and "headers" in tokens:
            user_agent = tokens["headers"].get("user-agent", "")
            
        cookies = parse_cookie_string(raw_cookie) if raw_cookie else None
                
        if not user_agent:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        from proxify.platforms.facebook.bridge import bridge
        if not cookies and not bridge.is_connected(threshold=60.0):
            logger.error("[Crawler] No cookies for page scrape")
            return 0

        progress["message"] = f"Đang tải trang {permalink[:50]}..."

        try:
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "vi,en;q=0.9",
                "User-Agent": user_agent,
            }
            if raw_cookie:
                headers["cookie"] = raw_cookie

            # Strategy 2: Directly fetch HTML page via native curl_cffi with Chrome120 fingerprint (0.4s response)
            resp = await self.network_client.safe_request(
                "GET", permalink,
                headers=headers,
                cookies=cookies,
                allow_redirects=True,
                timeout=15.0,
            )

            if not resp or resp.is_blocked:
                logger.warning(f"[Crawler] Blocked or empty response fetching {permalink}")
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


def is_any_comment_crawling() -> bool:
    """Check if any comment crawl is actively running or queued."""
    for prog in _default_crawler._comment_progress.values():
        if isinstance(prog, dict) and prog.get("status") in ("running", "queued"):
            return True
    return False


def is_post_crawling() -> bool:
    """Check if group feed post crawl is actively running."""
    return _default_crawler.crawl_state.get("status") in ("running", "fetching_template")


