"""
Facebook Crawler — Facade (ch13)
================================
Provides a unified API for all Facebook crawling operations.

Pattern: **Facade (ch13)** — delegates to specialized domain crawlers
(GroupCrawler, ProfileCrawler, CommentCrawler) via CrawlerEngine (ch36).

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
from proxify.platforms.facebook.auth import (
    get_saved_tokens,
    extract_templates,
    TENANT_COOKIES,
    IN_MEMORY_COOKIES,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
)
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper
from proxify.platforms.facebook.crawlers.engine import (
    CrawlerEngine,
    MockResponse,
    DisconnectedResponse,
    GRAPHQL_ENDPOINT as _ENGINE_GRAPHQL_ENDPOINT,
)
from proxify.platforms.facebook.crawlers.group import (
    GroupCrawler,
    DEFAULT_FEED_VARIABLES,
    resolve_numeric_group_id as _resolve_numeric_group_id_impl,
)
from proxify.platforms.facebook.crawlers.comment import (
    CommentCrawler,
    find_comment_ids as _find_comment_ids_impl,
)
from proxify.platforms.facebook.crawlers.profile import (
    ProfileCrawler,
    ProfileLockError,
)
from proxify.platforms.facebook.workflow import (
    state_observer,
    CrawlFeedCommand,
    CrawlProfileFeedCommand,
    RefreshCommand,
    CrawlCommentCommand,
)

logger = logging.getLogger("proxify.facebook.crawler")

# ─── Constants ──────────────────────────────────────────────────────────

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"
INTERNAL_PROXY = "http://127.0.0.1:8080"
MAX_PAGES_PER_SESSION = 100000
CONCURRENCY_LIMIT = 1  # Phase 3: Single API Worker (Mutex)

# DEFAULT_FEED_VARIABLES now lives in crawlers.group — re-exported for backward compat
# (imported above)



async def _resolve_numeric_group_id(group_id_or_slug: str, cookie: str, manager, client_id: str = "default") -> str:
    """Backward-compat wrapper — delegates to crawlers.group."""
    return await _resolve_numeric_group_id_impl(group_id_or_slug, cookie, manager, client_id)

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
        client_id: str = "default",
    ) -> None:
        self.client_id = client_id
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

        # Phase 1: CrawlerEngine — shared HTTP infrastructure (Delegation ch36)
        self._engine = CrawlerEngine(self)
        # Phase 2: GroupCrawler — group feed crawl (Delegation ch36)
        self._group = GroupCrawler(self._engine)
        # Phase 3: CommentCrawler — comment + metrics (Delegation ch36)
        self._comment = CommentCrawler(self._engine)
        # Phase 4: ProfileCrawler — personal profile timeline (Delegation ch36)
        self._profile = ProfileCrawler(self._engine)
        self._session_state = SessionStateManager()
        self._comment_session_state = SessionStateManager()
        self._feed_queue = asyncio.Queue()
        self._comment_queue = asyncio.Queue()
        self._command_queue = self._feed_queue  # Backward compatibility
        
        self._feed_worker_task: Optional[asyncio.Task] = None
        self._comment_worker_task: Optional[asyncio.Task] = None
        self._worker_task: Optional[asyncio.Task] = None

    def _ensure_feed_worker(self) -> None:
        """Lazily start the feed worker task if not already running."""
        if self._feed_worker_task is None or self._feed_worker_task.done():
            self._feed_worker_task = asyncio.create_task(self._feed_worker_loop())
            self._worker_task = self._feed_worker_task

    def _ensure_comment_worker(self) -> None:
        """Lazily start the comment worker task if not already running."""
        if self._comment_worker_task is None or self._comment_worker_task.done():
            self._comment_worker_task = asyncio.create_task(self._comment_worker_loop())

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
        """Delegate to CrawlerEngine.safe_request (Delegation ch36)."""
        return await self._engine.safe_request(method, url, **kwargs)

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
        self._ensure_feed_worker()
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
        """Delegate to GroupCrawler.execute_crawl_feed (Delegation ch36)."""
        await self._group.execute_crawl_feed(
            group_id, start_timestamp, end_timestamp,
            template, client_cookie, reset_cursor,
        )

    async def crawl_profile_feed(
        self,
        profile_id: str,
        start_timestamp: int,
        end_timestamp: int,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
    ) -> None:
        """Facade: Enqueues a CrawlProfileFeedCommand to the feed worker."""
        self._stop_flag = False
        self._ensure_feed_worker()
        cmd = CrawlProfileFeedCommand(self, profile_id, start_timestamp, end_timestamp, template, client_cookie)
        await self._feed_queue.put(cmd)

    async def _execute_crawl_profile_feed(
        self,
        profile_id: str,
        start_timestamp: int,
        end_timestamp: int,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
    ) -> None:
        """Delegate to ProfileCrawler.execute_crawl_profile_feed (Delegation ch36)."""
        await self._profile.execute_crawl_profile_feed(
            profile_id, start_timestamp, end_timestamp,
            template, client_cookie,
        )

    async def crawl_specific_posts(self, urls: list[str], template: Optional[dict] = None, client_cookie: Optional[str] = None) -> dict:
        """Facade: Enqueues a RefreshCommand to the API worker."""
        self._ensure_feed_worker()
        cmd = RefreshCommand(self, urls, template, client_cookie)
        await self._command_queue.put(cmd)
        return {"status": "ok", "message": "Crawler queued"}

    async def _execute_crawl_specific_posts(self, urls: list[str], template: Optional[dict] = None, client_cookie: Optional[str] = None) -> dict:
        """Crawl specific post URLs to refresh metrics (reactions, comments).
        Uses safe GraphQL and anonymous checks. ZERO in-tab HTML fetching.
        """
        logger.info(f"[Crawler] Refreshing {len(urls)} posts safely via GraphQL/anonymous check")
        self.refresh_progress.update(total=len(urls), current=0, status="running")

        try:
            sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
            
            async def _refresh_url(url: str):
                async with sem:
                    self.refresh_progress["current"] = min(self.refresh_progress["current"] + 1, len(urls))
                    try:
                        post_id = None
                        feedback_id = None
                        with shared_pool.cursor(dict_cursor=True) as cur:
                            cur.execute(
                                "SELECT post_id, feedback_id FROM facebook.posts WHERE permalink_url = %s",
                                (url,)
                            )
                            row = cur.fetchone()
                            if row:
                                post_id = row["post_id"]
                                feedback_id = row.get("feedback_id")
                                
                        if not post_id:
                            import re
                            m = re.search(r'/(?:posts|videos|permalink)/(\d+)', url)
                            if not m:
                                m = re.search(r'[?&]fbid=(\d+)', url)
                            if m:
                                post_id = m.group(1)
                                
                        if post_id:
                            await self.refresh_single_post(
                                post_id=post_id,
                                feedback_id=feedback_id,
                                permalink=url,
                                template=template,
                                client_cookie=client_cookie,
                                client_id=self.client_id
                            )
                        else:
                            logger.warning(f"[Crawler] Could not extract post_id for URL: {url}")
                            
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        logger.error(f"[Crawler] Error refreshing post {url}: {e}")

            await asyncio.gather(*[_refresh_url(u) for u in urls])
            logger.info("[Crawler] Safe post refresh completed.")
            return {"status": "ok", "message": "Crawler finished"}

        except Exception as e:
            logger.error(f"[Crawler] Fatal error in refresh: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self.refresh_progress["status"] = "idle"

    async def refresh_single_post(
        self,
        post_id: str,
        feedback_id: Optional[str] = None,
        permalink: Optional[str] = None,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
        client_id: str = "default",
    ) -> dict:
        """Refresh reaction count, comment count, and active status for a single post.
        
        CRITICAL ARCHITECTURAL SAFETY GUARANTEE:
        - Strictly forbids in-tab HTML fetching to prevent account checkpoints.
        - Primary: Anonymous curl_cffi GET request (ZERO COOKIES) to inspect public permalink.
        - Fallback: Uses GraphQL (CommentListComponentsRootQuery/CommentsListComponentsPaginationQuery) via Extension Bridge.
        """
        self.client_id = client_id
        target_fbid = feedback_id
        target_permalink = permalink
        group_id = None

        # Lookup missing metadata from DB
        try:
            with shared_pool.cursor(dict_cursor=True) as cur:
                cur.execute(
                    "SELECT feedback_id, permalink_url, group_id, group_numeric_id FROM facebook.posts WHERE post_id = %s",
                    (post_id,)
                )
                row = cur.fetchone()
                if row:
                    if not target_fbid and row.get("feedback_id"):
                        target_fbid = row["feedback_id"]
                    if not target_permalink and row.get("permalink_url"):
                        target_permalink = row["permalink_url"]
                    group_id = row.get("group_id") or row.get("group_numeric_id")
        except Exception as e:
            logger.debug(f"[Refresh] DB lookup error for {post_id}: {e}")

        # Derive permalink if still missing
        if not target_permalink and post_id:
            raw_pid = post_id.split("_")[-1] if "_" in post_id else post_id
            if group_id:
                target_permalink = f"https://www.facebook.com/groups/{group_id}/posts/{raw_pid}/"
            else:
                target_permalink = f"https://www.facebook.com/{raw_pid}"

        # Derive feedback_id if still missing
        if not target_fbid and post_id:
            raw_pid = post_id.split("_")[-1] if "_" in post_id else post_id
            try:
                import base64
                target_fbid = base64.b64encode(f"feedback:{raw_pid}".encode()).decode()
            except Exception:
                pass

        # ── 1. Primary path: Anonymous curl_cffi check (ZERO COOKIES) ─────
        if target_permalink:
            try:
                from curl_cffi.requests import AsyncSession
                from proxify.platforms.facebook.api import IN_MEMORY_COOKIES
                ua = IN_MEMORY_COOKIES.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                headers = {
                    "user-agent": ua,
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "accept-language": "vi,en;q=0.9",
                }
                async with AsyncSession(impersonate="chrome120") as s:
                    r = await s.get(target_permalink, headers=headers, timeout=12)
                    rc, cc, resolved_fbid, is_active, status = self.extract_metrics_from_html(r.text)
                    
                    if not is_active:
                        with shared_pool.cursor() as cur:
                            cur.execute(
                                "UPDATE facebook.posts SET is_active = FALSE, updated_at = NOW() WHERE post_id = %s",
                                (post_id,)
                            )
                        logger.info(f"[Refresh] Post {post_id} marked as inactive/deleted via anonymous check")
                        return {"updated": True, "is_active": False}
                        
                    if status == "ok":
                        with shared_pool.cursor() as cur:
                            updates = ["is_active = TRUE", "updated_at = NOW()"]
                            params = []
                            if rc is not None:
                                updates.append("reaction_count = %s")
                                params.append(rc)
                            if cc is not None:
                                updates.append("comment_count = %s")
                                params.append(cc)
                            if resolved_fbid:
                                updates.append("feedback_id = %s")
                                params.append(resolved_fbid)
                            params.append(post_id)
                            cur.execute(
                                f"UPDATE facebook.posts SET {', '.join(updates)} WHERE post_id = %s",
                                params
                            )
                        logger.info(
                            f"[Refresh] Post {post_id} updated via anonymous permalink: "
                            f"reactions={rc}, comments={cc}, active=True, feedback_id={resolved_fbid or target_fbid}"
                        )
                        return {
                            "updated": True,
                            "is_active": True,
                            "reaction_count": rc,
                            "comment_count": cc,
                        }
            except Exception as e:
                logger.warning(f"[Refresh] Anonymous permalink check failed for post {post_id}: {e}")

        # ── 2. Fallback path: GraphQL query via Extension Bridge ───────────
        tokens = template or await get_saved_tokens(self.client_id) or {}
        comment_tpl = tokens.get("comment")
        feed_tpl = tokens.get("feed")
        if not comment_tpl and target_fbid:
            comment_tpl = self._synthesize_comment_template(target_fbid, feed_tpl)

        if comment_tpl and target_fbid:
            try:
                _, resp_text, _, _, _ = await self._fetch_comments(
                    target_fbid, comment_tpl, cursor=None, direction="after"
                )
                if resp_text:
                    r_count, c_count, resolved_fbid, is_active = self._parse_metrics_from_graphql(resp_text)
                    
                    with shared_pool.cursor() as cur:
                        updates = ["is_active = %s", "updated_at = NOW()"]
                        params = [is_active]
                        if r_count is not None:
                            updates.append("reaction_count = %s")
                            params.append(r_count)
                        if c_count is not None:
                            updates.append("comment_count = %s")
                            params.append(c_count)
                        if resolved_fbid:
                            updates.append("feedback_id = %s")
                            params.append(resolved_fbid)
                        params.append(post_id)
                        
                        cur.execute(
                            f"UPDATE facebook.posts SET {', '.join(updates)} WHERE post_id = %s",
                            params
                        )

                    logger.info(
                        f"[Refresh] Post {post_id} updated via GraphQL: reactions={r_count}, comments={c_count}, "
                        f"active={is_active}, feedback_id={resolved_fbid or target_fbid}"
                    )
                    return {
                        "updated": True,
                        "is_active": is_active,
                        "reaction_count": r_count,
                        "comment_count": c_count,
                    }
            except Exception as e:
                logger.warning(f"[Refresh] GraphQL query fallback failed for post {post_id}: {e}")

        return {"updated": False, "is_active": None}

    # ═══════════════════════════════════════════════════════════════════
    #  Private Helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    async def _resolve_cookie(
        client_cookie: Optional[str],
        tokens: Optional[dict] = None,
        client_id: str = "default",
    ) -> str:
        """Delegate to CrawlerEngine.resolve_cookie (Delegation ch36)."""
        return await CrawlerEngine.resolve_cookie(client_cookie, tokens, client_id)

    @staticmethod
    def _build_headers(feed_tpl: dict, cookie: str, group_id: str) -> dict:
        """Delegate to CrawlerEngine.build_headers (Delegation ch36)."""
        return CrawlerEngine.build_headers(feed_tpl, cookie, group_id)

    @staticmethod
    def _set_variables(data: dict, group_id: str, cursor: str) -> Optional[str]:
        """Delegate to GroupCrawler.set_variables (Delegation ch36)."""
        return GroupCrawler.set_variables(data, group_id, cursor)

    @staticmethod
    def _check_old_posts(
        resp_text: str, start_ts: int, consecutive: int,
    ) -> tuple[bool, int, list[int]]:
        """Delegate to GroupCrawler.check_old_posts (Delegation ch36)."""
        return GroupCrawler.check_old_posts(resp_text, start_ts, consecutive)

    @staticmethod
    def _extract_cursor(resp_text: str) -> str:
        """Delegate to CrawlerEngine.extract_cursor (Delegation ch36)."""
        return CrawlerEngine.extract_cursor(resp_text)

    async def _fetch_comments_for_page(
        self,
        resp_text: str,
        comment_tpl: dict,
        reply_tpl: Optional[dict],
        collected: list[str],
    ) -> None:
        """Fetch comments and replies for all stories in a page response."""
        feedback_ids = CommentCrawler.extract_feedback_ids(resp_text)
        if not feedback_ids:
            return

        sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def _process(fid: str) -> None:
            async with sem:
                logger.info(f"[Crawler] Fetching comments for {fid}")
                res = await self._comment.fetch_comments(
                    fid, comment_tpl, self._comment_session_state
                )
                c_ids, c_text = res[0], res[1]
                if c_text:
                    collected.append(c_text)
                if reply_tpl and c_ids:
                    for cid in c_ids:
                        logger.info(f"[Crawler] Fetching replies for {cid}")
                        r_text = await self._comment.fetch_replies(
                            cid, reply_tpl, self._comment_session_state
                        )
                        if r_text:
                            collected.append(r_text)
                        await asyncio.sleep(comment_delay(self.delay_config))
                await asyncio.sleep(comment_delay(self.delay_config))

        await asyncio.gather(*(_process(fid) for fid in feedback_ids))

    @staticmethod
    def _extract_feedback_ids(resp_text: str) -> list[str]:
        """Delegate to CommentCrawler.extract_feedback_ids (Delegation ch36)."""
        return CommentCrawler.extract_feedback_ids(resp_text)

    @staticmethod
    def _extract_comment_page_info(
        resp_text: str, current_direction: str = "after"
    ) -> tuple[Optional[str], bool, str]:
        """Delegate to CommentCrawler.extract_comment_page_info (Delegation ch36)."""
        return CommentCrawler.extract_comment_page_info(resp_text, current_direction)

    async def _fetch_comments(
        self, feedback_id: str, template: dict, cursor: Optional[str] = None, direction: str = "after"
    ) -> tuple[list[str], str, Optional[str], bool, str]:
        """Delegate to CommentCrawler.fetch_comments (Delegation ch36)."""
        return await self._comment.fetch_comments(
            feedback_id, template, self._comment_session_state, cursor, direction
        )

    async def _fetch_replies(self, comment_id: str, template: dict) -> str:
        """Delegate to CommentCrawler.fetch_replies (Delegation ch36)."""
        return await self._comment.fetch_replies(
            comment_id, template, self._comment_session_state
        )

    @staticmethod
    def _parse_comment_ids(resp_text: str) -> list[str]:
        """Delegate to CommentCrawler.parse_comment_ids (Delegation ch36)."""
        return CommentCrawler.parse_comment_ids(resp_text)

    def _synthesize_feed_template(
        self,
        group_id: str,
        raw_cookie: Optional[str] = None,
        client_id: str = "default",
    ) -> Optional[dict]:
        """Delegate to GroupCrawler.synthesize_feed_template (Delegation ch36)."""
        return self._group.synthesize_feed_template(group_id, raw_cookie, client_id)

    def _synthesize_comment_template(self, feedback_id: str, feed_tpl: Optional[dict] = None) -> dict:
        """Delegate to CommentCrawler.synthesize_comment_template (Delegation ch36)."""
        return self._comment.synthesize_comment_template(feedback_id, feed_tpl)

    @staticmethod
    def extract_metrics_from_html(html: str) -> tuple[Optional[int], Optional[int], Optional[str], bool, str]:
        """Delegate to CommentCrawler.extract_metrics_from_html (Delegation ch36)."""
        return CommentCrawler.extract_metrics_from_html(html)

    @staticmethod
    def _parse_metrics_from_graphql(resp_text: str) -> tuple[Optional[int], Optional[int], Optional[str], bool]:
        """Delegate to CommentCrawler.parse_metrics_from_graphql (Delegation ch36)."""
        return CommentCrawler.parse_metrics_from_graphql(resp_text)

    def _update_post_metrics(self, url: str, html: str) -> None:
        """Delegate to CommentCrawler.update_post_metrics (Delegation ch36)."""
        self._comment.update_post_metrics(url, html)

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
        self._ensure_comment_worker()
            
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
            tokens = template or await get_saved_tokens(self.client_id) or {}
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
                comment_tpl = self._synthesize_comment_template(feedback_id, feed_tpl)

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
                
                if not raw_cookie and not bridge.is_connected(client_id=self.client_id, threshold=60.0):
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
        tokens = tokens or await get_saved_tokens(self.client_id) or {}
        raw_cookie = await self._resolve_cookie(client_cookie, tokens, client_id=self.client_id)
        
        user_agent = ""
        if tokens and "headers" in tokens:
            user_agent = tokens["headers"].get("user-agent", "")
            
        cookies = parse_cookie_string(raw_cookie) if raw_cookie else None
                
        if not user_agent:
            from proxify.platforms.facebook.api import IN_MEMORY_COOKIES
            user_agent = IN_MEMORY_COOKIES.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        from proxify.platforms.facebook.bridge import bridge
        if not cookies and not bridge.is_connected(client_id=self.client_id, threshold=60.0):
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

            # Strategy 2: Safely fetch HTML page via Extension Bridge (In-Tab) to prevent logout
            resp = await self._safe_request(
                "GET", permalink,
                headers=headers,
                is_comment_crawl=True,
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
    """Backward-compat wrapper — delegates to crawlers.comment."""
    return _find_comment_ids_impl(obj)


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
    client_id: str = "default",
) -> None:
    """Module-level alias for ``FacebookCrawler.crawl_group_feed``."""
    _default_crawler.client_id = client_id
    await _default_crawler.crawl_group_feed(
        group_id, start_timestamp, end_timestamp, template, client_cookie, reset_cursor
    )


async def crawl_specific_posts(urls: list[str]) -> dict:
    """Module-level alias for ``FacebookCrawler.crawl_specific_posts``."""
    return await _default_crawler.crawl_specific_posts(urls)


async def crawl_post_comments(
    post_id: str, feedback_id: str, client_cookie: Optional[str] = None, client_id: str = "default",
) -> dict:
    """Module-level alias for ``FacebookCrawler.crawl_comments_for_post``."""
    _default_crawler.client_id = client_id
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


async def start_profile_crawler(
    profile_id: str,
    start_timestamp: int,
    end_timestamp: int,
    template: Optional[dict] = None,
    client_cookie: Optional[str] = None,
    client_id: str = "default",
) -> None:
    """Module-level alias for ``FacebookCrawler.crawl_profile_feed``."""
    _default_crawler.client_id = client_id
    await _default_crawler.crawl_profile_feed(
        profile_id, start_timestamp, end_timestamp, template, client_cookie
    )

