"""
Group Crawler — Facebook Group Feed Crawling
=============================================
Domain crawler for Facebook Group feed (Delegation target).

Pattern: **Delegation (ch36)** — ``GroupCrawler`` HAS-A ``CrawlerEngine``
(injected via Constructor Injection ch35).

Responsibilities:
- Execute paginated group feed crawl via GroupsCometFeedRegularStoriesPaginationQuery
- Synthesize feed template from DB / in-memory tokens when Extension hasn't captured one
- Set GraphQL variables (sorting, cursor, group ID)
- Detect old posts boundary for date-range stop condition
- Resolve group slug to numeric ID
"""

import asyncio
import json
import logging
import re
import statistics
import time
import urllib.parse
from datetime import datetime
from typing import Optional

from proxify.database import pool as shared_pool
from proxify.utils.stealth import StealthRequestError
from proxify.utils.circuit_breaker import crawl_breaker
from proxify.platforms.facebook.stealth import (
    SessionStateManager,
    page_delay,
)
from proxify.platforms.facebook.auth import (
    extract_templates,
    get_saved_tokens,
    TENANT_COOKIES,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
    IN_MEMORY_COOKIES,
)
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper

logger = logging.getLogger("proxify.facebook.crawlers.group")

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"
MAX_PAGES_PER_SESSION = 100000

DEFAULT_FEED_VARIABLES = {
    "count": 3,
    "cursor": None,
    "feedLocation": "GROUP",
    "feedType": "DISCUSSION",
    "feedbackSource": 0,
    "filterTopicId": None,
    "focusCommentID": None,
    "privacySelectorRenderLocation": "COMET_STREAM",
    "referringStoryRenderLocation": None,
    "renderLocation": "group",
    "scale": 1,
    "sortingSetting": "CHRONOLOGICAL",
    "stream_initial_count": 1,
    "useDefaultActor": False,
    "id": "0",
    "__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider": True,
    "__relay_internal__pv__GHLShouldChangeSponsoredDataFieldNamerelayprovider": True,
    "__relay_internal__pv__CometFeedStory_enable_reactor_facepilerelayprovider": False,
    "__relay_internal__pv__CometFeedStory_enable_social_bubblesrelayprovider": False,
    "__relay_internal__pv__CometFeedStory_enable_post_permalink_white_space_clickrelayprovider": False,
    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
    "__relay_internal__pv__IsWorkUserrelayprovider": False,
    "__relay_internal__pv__TestPilotShouldIncludeDemoAdUseCaserelayprovider": False,
    "__relay_internal__pv__FBReels_deprecate_short_form_video_context_gkrelayprovider": True,
    "__relay_internal__pv__FBReels_enable_view_dubbed_audio_type_gkrelayprovider": True,
    "__relay_internal__pv__CometFeedShareMedia_shouldPrefetchShareImagerelayprovider": False,
    "__relay_internal__pv__CometImmersivePhotoCanUserDisable3DMotionrelayprovider": False,
    "__relay_internal__pv__WorkCometIsEmployeeGKProviderrelayprovider": False,
    "__relay_internal__pv__IsMergQAPollsrelayprovider": False,
    "__relay_internal__pv__FBReelsMediaFooter_comet_enable_reels_ads_gkrelayprovider": True,
    "__relay_internal__pv__CometUFIReactionsEnableShortNamerelayprovider": False,
    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
    "__relay_internal__pv__CometUFIShareActionMigrationrelayprovider": True,
    "__relay_internal__pv__CometUFISingleLineUFIrelayprovider": True,
    "__relay_internal__pv__relay_provider_comet_ufi_ssr_seo_deferrelayprovider": True,
    "__relay_internal__pv__CometUFI_dedicated_comment_routable_dialog_gkrelayprovider": True,
    "__relay_internal__pv__ReelsIFUCard_reelsIFULikeCountrelayprovider": False,
    "__relay_internal__pv__FBReelsIFUTileContent_reelsIFUPlayOnHoverrelayprovider": True,
    "__relay_internal__pv__GroupsCometGYSJFeedItemHeightrelayprovider": 206,
    "__relay_internal__pv__StoriesShouldEnablePhotosensitiveContentWarningrelayprovider": False,
    "__relay_internal__pv__ShouldEnableBakedInTextStoriesrelayprovider": False,
    "__relay_internal__pv__StoriesShouldIncludeFbNotesrelayprovider": True,
}


# ─── Resolve Numeric Group ID ───────────────────────────────────────

async def resolve_numeric_group_id(
    group_id_or_slug: str, cookie: str, manager, client_id: str = "default"
) -> str:
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
        logger.warning(f"[GroupCrawler] Lỗi đọc DB nhóm: {e}")

    url = f"https://www.facebook.com/groups/{group_id_or_slug}"

    # Giải mã an toàn qua curl_cffi KHÔNG mang cookie
    try:
        from curl_cffi.requests import AsyncSession
        from proxify.platforms.facebook.api import IN_MEMORY_COOKIES as API_COOKIES
        ua = API_COOKIES.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        headers = {
            "user-agent": ua,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "vi,en;q=0.9",
        }
        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(url, headers=headers, timeout=12)
            text = resp.text
            if text:
                match = re.search(r'"groupID":"(\d+)"', text)
                if not match:
                    match = re.search(r'(?:groupID|group_id|targetID)["\'\\\]*:\s*["\'\\\]*(\d+)', text)
                if match:
                    numeric_id = match.group(1)
                    logger.info(f"[GroupCrawler] Resolved slug '{group_id_or_slug}' -> Numeric ID '{numeric_id}'")
                    try:
                        from proxify.platforms.facebook.database import fb_db
                        with fb_db.pool.cursor() as cur:
                            cur.execute(
                                "INSERT INTO facebook.groups (group_id, slug) VALUES (%s, %s) ON CONFLICT (group_id) DO NOTHING",
                                (numeric_id, group_id_or_slug)
                            )
                    except Exception:
                        pass
                    return numeric_id
    except Exception as e:
        logger.warning(f"[GroupCrawler] Lỗi phân giải slug qua curl_cffi: {e}")

    # Fallback to returning original if failed
    return group_id_or_slug


# ─── GroupCrawler ────────────────────────────────────────────────────

class GroupCrawler:
    """Facebook Group feed crawler — Delegation target (ch36).

    HAS-A ``CrawlerEngine`` (composition, NOT inheritance).
    Injected via Constructor Injection (ch35).

    Responsibilities:
    - Paginated group feed crawl (CHRONOLOGICAL sort)
    - Feed template synthesis
    - Old-posts boundary detection
    - GraphQL variable management
    """

    def __init__(self, engine) -> None:
        self.engine = engine

    # ── Execute Crawl Feed ───────────────────────────────────────────

    async def execute_crawl_feed(
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
            reset_cursor: Reset pagination cursor for fresh crawl.
        """
        facade = self.engine.facade

        # ── Resolve cookie ──────────────────────────────────────────
        raw_cookie = await self.engine.resolve_cookie(client_cookie, template, client_id=facade.client_id)

        # ── Load templates ──────────────────────────────────────────
        tokens = template or await get_saved_tokens(facade.client_id)
        feed_tpl, comment_tpl, reply_tpl = extract_templates(tokens) if tokens else (None, None, None)

        # Autonomous Synthetic Fallback
        if not feed_tpl or "form_data" not in feed_tpl:
            logger.info(f"[GroupCrawler] feed_tpl not found for '{facade.client_id}'. Synthesizing...")
            feed_tpl = self.synthesize_feed_template(group_id, raw_cookie=raw_cookie, client_id=facade.client_id)

        if not feed_tpl or "form_data" not in feed_tpl:
            logger.error("No FB Feed template found. Browse a Facebook Group through Proxify first.")
            facade.crawl_state.update(
                status="error",
                message=(
                    "❌ Extension chưa bắt được gói tin GraphQL thực.\n\n"
                    "⚠️ Hướng dẫn khắc phục:\n"
                    "1. Vui lòng mở Facebook trong trình duyệt.\n"
                    "2. Mở Extension Proxify và bấm 'Lấy Cookie & Token'.\n"
                    "3. Hoặc truy cập vào MỘT NHÓM FACEBOOK BẤT KỲ và cuộn chuột lướt xuống vài bài viết.\n"
                    "4. Sau đó quay lại đây và bấm 'Bắt đầu thu thập' một lần nữa!"
                )
            )
            return

        logger.info(
            f"Starting crawler for Group {group_id}, "
            f"date_range=[{start_timestamp}, {end_timestamp}]"
        )

        numeric_group_id = await resolve_numeric_group_id(group_id, raw_cookie, facade.manager)
        if numeric_group_id != group_id:
            logger.info(f"Resolved group slug '{group_id}' -> Numeric ID '{numeric_group_id}'")

        if not raw_cookie:
            facade.crawl_state.update(
                status="error",
                message="❌ Không tìm thấy cookies Facebook.\nHãy paste cookie vào ô 'Facebook Cookie' trên giao diện hoặc bấm 'Lấy Cookie & Token' trên Extension.",
            )
            return

        # ── Kiểm tra kết nối Extension Bridge ───────────────────────
        from proxify.platforms.facebook.bridge import bridge
        if not bridge.is_connected(client_id=facade.client_id, threshold=60.0):
            logger.warning("[GroupCrawler] Chrome Extension offline before crawl start.")
            facade.crawl_state.update(
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
        facade.crawl_state.update(
            status="running",
            group_id=group_id,
            message=f"[SUCCESS] Tiến trình đang chạy ngầm cho Group ID: {group_id}...\nDữ liệu sẽ tự động xuất hiện bên dưới.",
        )

        headers = self.engine.build_headers(feed_tpl, raw_cookie, numeric_group_id)
        form_data_template = feed_tpl.get("form_data", {}).copy()

        # INJECT FRESH TOKENS from Extension ONLY if missing from template
        from proxify.platforms.facebook.api import IN_MEMORY_COOKIES as API_COOKIES
        fresh_fb_dtsg = API_COOKIES.get("fb_dtsg")
        fresh_lsd = API_COOKIES.get("lsd")
        if fresh_fb_dtsg and not form_data_template.get("fb_dtsg"):
            form_data_template["fb_dtsg"] = fresh_fb_dtsg
            form_data_template["jazoest"] = "2" + str(sum(ord(c) for c in fresh_fb_dtsg))
        if fresh_lsd and not form_data_template.get("lsd"):
            form_data_template["lsd"] = fresh_lsd

        c_user_match = re.search(r'c_user=([^;]+)', raw_cookie)
        if c_user_match and not form_data_template.get("__user"):
            form_data_template["__user"] = c_user_match.group(1)
        elif API_COOKIES.get("user_id") and not form_data_template.get("__user"):
            form_data_template["__user"] = API_COOKIES["user_id"]

        fresh_sd = API_COOKIES.get("sd")
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
            if facade._stop_flag:
                logger.info("[GroupCrawler] Stop flag detected. Breaking feed loop.")
                break

            # Circuit breaker gate
            if not crawl_breaker.allow_request():
                remaining = crawl_breaker.remaining_cooldown
                logger.warning(f"[GroupCrawler] Circuit breaker OPEN — cooldown: {remaining / 60:.0f}min")
                facade.crawl_state.update(
                    status="paused",
                    message=f"⚠️ Phát hiện block từ Facebook. Tạm dừng crawl.\nTự động tiếp tục sau {remaining / 60:.0f} phút.",
                )
                break

            # Build form data with dynamic session params
            data = form_data_template.copy()
            session_state.update_params(data)
            cursor = self.set_variables(data, numeric_group_id, cursor)
            if cursor is None:  # parse error
                break

            try:
                facade.crawl_state.update(
                    message=f"🚀 Đang thu thập trang {page_num + 1}...\nChờ xíu nha!",
                    last_p_count=0,
                    last_c_count=0,
                    updated_at=time.time()
                )
                logger.info(f"[GroupCrawler] Page {page_num + 1}, cursor: {cursor[:50]}...")
                resp = await self.engine.safe_request(
                    "POST", GRAPHQL_ENDPOINT,
                    headers=headers,
                    data=urllib.parse.urlencode(data).encode(),
                )
                resp_text = resp.text
                collected = [resp_text]

                logger.info(
                    f"[GroupCrawler] Page {page_num + 1}: status={resp.status_code}, "
                    f"len={len(resp_text)}, blocked={resp.is_blocked}"
                )

                # Check for Facebook JSON errors
                stripped_resp = resp_text.strip()
                if stripped_resp.startswith("for (;;);") or stripped_resp.startswith('{"errors"'):
                    try:
                        raw_json_str = stripped_resp[9:] if stripped_resp.startswith("for (;;);") else stripped_resp
                        first_line = raw_json_str.split('\n')[0]
                        json_data = json.loads(first_line)
                        if "errors" in json_data and isinstance(json_data["errors"], list) and json_data["errors"]:
                            first_err = json_data["errors"][0]
                            err_msg = first_err.get("message", "GraphQL Server Error")
                            err_code = first_err.get("code", 0)
                            logger.error(f"[GroupCrawler] GraphQL error {err_code}: {err_msg}")
                            facade.crawl_state.update(
                                status="error",
                                message=f"❌ Lỗi GraphQL Facebook ({err_code}): {err_msg}",
                            )
                            break
                        if "error" in json_data and isinstance(json_data["error"], int):
                            error_code = json_data["error"]
                            error_summary = json_data.get("errorSummary", "Unknown error")
                            logger.error(f"[GroupCrawler] GraphQL error {error_code}: {error_summary}")
                            logger.error(f"[GroupCrawler] Full error response: {stripped_resp[:2000]}")
                            error_desc = json_data.get("errorDescription", "")
                            if error_code == 1357001:
                                if error_desc and "thành viên" in error_desc:
                                    msg = f"❌ {error_summary}.\n{error_desc}"
                                else:
                                    msg = "❌ Cookie đã hết hạn hoặc bị lỗi xác thực (Error 1357001).\nVui lòng cập nhật lại cookie mới."
                                facade.crawl_state.update(
                                    status="error",
                                    message=msg,
                                )
                            else:
                                facade.crawl_state.update(
                                    status="error",
                                    message=f"❌ Lỗi truy vấn Facebook (Code {error_code}): {error_summary}\nVui lòng kiểm tra lại Cookie/Tài khoản.",
                                )
                            break
                    except Exception as e:
                        logger.error(f"[GroupCrawler] Error parsing GraphQL JSON: {e}, snippet: {resp_text[:100]}")
                        pass

                # Check for Extension disconnection or stop flag
                if getattr(resp, "is_disconnected", False) or facade._stop_flag:
                    logger.warning("[GroupCrawler] Disconnected or stop flag set. Halting.")
                    break

                # Soft-block → trip circuit breaker and stop
                if resp.is_blocked:
                    crawl_breaker.trip(f"Soft-block on page {page_num + 1} (status={resp.status_code})")
                    facade.crawl_state.update(
                        status="blocked",
                        message=f"🛑 Facebook đã block request ở page {page_num + 1}.\nCrawler đã dừng. Cooldown {crawl_breaker.remaining_cooldown / 60:.0f} phút.",
                    )
                    break

                crawl_breaker.record_success()

                # Extract data from collected responses
                timestamps = []
                should_stop = False
                try:
                    variables = json.loads(data.get("variables", "{}"))
                    cached_name = facade._group_name_cache.get(group_id)
                    p_count, c_count, detected_name = extract_from_responses(
                        collected, variables,
                        group_id=group_id,
                        group_name=cached_name,
                        start_ts=start_timestamp,
                        end_ts=end_timestamp,
                        group_numeric_id=numeric_group_id,
                    )
                    # Cache detected name
                    if detected_name and not cached_name:
                        facade._group_name_cache[group_id] = detected_name
                        logger.info(f"[GroupCrawler] Cached group_name: {detected_name}")
                    logger.info(f"[GroupCrawler] Page {page_num + 1}: {p_count} posts, {c_count} comments")

                    # Check for old posts
                    should_stop, consecutive_old_pages, timestamps = self.check_old_posts(
                        resp_text, start_timestamp, consecutive_old_pages,
                    )

                    # Format progress date
                    progress_msg = ""
                    if timestamps:
                        median_ts = statistics.median(timestamps)
                        median_date = datetime.fromtimestamp(median_ts).strftime('%d/%m/%Y')
                        progress_msg = f"\n(Đang quét bài viết quanh ngày {median_date})"

                    facade.crawl_state.update(
                        message=f"🚀 Đang thu thập trang {page_num + 1}...{progress_msg}",
                        last_p_count=p_count,
                        last_c_count=c_count,
                        updated_at=time.time()
                    )
                except Exception as e:
                    logger.error(f"[GroupCrawler] Extraction failed: {e}")

                # Stop condition: reached old posts threshold
                if should_stop:
                    logger.info("[GroupCrawler] Reached old posts threshold. Stopping.")
                    break

                # Extract next cursor
                cursor = self.engine.extract_cursor(resp_text)
                if not cursor:
                    logger.info("[GroupCrawler] No more cursor. Stopping.")
                    fb_db.config.set(f"crawl_cursor_{group_id}", "")
                    break
                else:
                    fb_db.config.set(f"crawl_cursor_{group_id}", cursor)

                # Human-like delay
                delay = page_delay(facade.delay_config)
                logger.info(f"[GroupCrawler] Delay: {delay:.1f}s")
                await asyncio.sleep(delay)

            except StealthRequestError as e:
                logger.error(f"[GroupCrawler] Request failed: {e}")
                await asyncio.sleep(10)
                continue
            except Exception as e:
                logger.error(f"[GroupCrawler] Unexpected error: {e}")
                break

        # ── Finish ──────────────────────────────────────────────────
        stats = facade.manager.stats
        logger.info(
            f"Crawler finished. requests={stats['total_requests']}, "
            f"blocks={stats['total_blocks']}, block_rate={stats['block_rate']}"
        )
        if facade.crawl_state.get("status") == "running":
            facade.crawl_state.update({
                "status": "idle",
                "message": f"Hoàn tất thu thập cho Group ID: {group_id}",
            })

    # ── Static Helpers ───────────────────────────────────────────────

    @staticmethod
    def set_variables(data: dict, group_id: str, cursor: str) -> Optional[str]:
        """Set GraphQL variables in form data. Returns cursor or None on error."""
        try:
            variables = json.loads(data.get("variables", "{}"))

            # Ensure base required fields exist if template variables were sparse
            for k, v in DEFAULT_FEED_VARIABLES.items():
                if k not in variables:
                    variables[k] = v

            # Bắt buộc sắp xếp theo thời gian đăng bài (CHRONOLOGICAL)
            variables["sortingSetting"] = "CHRONOLOGICAL"
            variables["id"] = group_id
            if cursor:
                variables["cursor"] = cursor
            else:
                variables["cursor"] = None
            data["variables"] = json.dumps(variables, separators=(",", ":"))
            return cursor
        except Exception as e:
            logger.error(f"[GroupCrawler] Failed to parse variables: {e}")
            return None

    @staticmethod
    def check_old_posts(
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

        if all(t < start_ts for t in timestamps):
            consecutive += 1
            logger.info(f"[GroupCrawler] Old posts detected ({len(timestamps)} posts older than {start_ts}). Consecutive: {consecutive}/3")
            if consecutive >= 3:
                return True, consecutive, timestamps
        else:
            consecutive = 0

        return False, consecutive, timestamps

    # ── Synthesize Feed Template ─────────────────────────────────────

    def synthesize_feed_template(
        self,
        group_id: str,
        raw_cookie: Optional[str] = None,
        client_id: str = "default",
    ) -> Optional[dict]:
        """Generate a synthetic GroupsCometFeedRegularStoriesPaginationQuery template
        from past database requests, memory, or stable baseline."""
        tenant_cookie = TENANT_COOKIES.get(client_id, {})
        base_form = {}
        base_headers = {}

        # 1. Try to find recent GroupsCometFeed in requests table
        try:
            with shared_pool.cursor() as cur:
                cur.execute("""
                    SELECT request_body, request_headers::jsonb
                    FROM requests
                    WHERE (graphql_operation = 'GroupsCometFeedRegularStoriesPaginationQuery'
                           OR request_body LIKE '%GroupsCometFeedRegularStoriesPaginationQuery%')
                      AND status_code = 200 AND length(response_body) > 500
                    ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                if not row:
                    cur.execute("""
                        SELECT request_body, request_headers::jsonb
                        FROM requests
                        WHERE url LIKE '%facebook.com/api/graphql%'
                          AND (graphql_operation ILIKE '%Feed%' OR request_body LIKE '%fb_dtsg=%')
                          AND status_code = 200
                        ORDER BY id DESC LIMIT 1
                    """)
                    row = cur.fetchone()

                if row and row[0]:
                    parsed = urllib.parse.parse_qs(row[0])
                    for k, vals in parsed.items():
                        if vals:
                            base_form[k] = vals[0]
                    if row[1] and isinstance(row[1], dict):
                        base_headers = row[1].copy()

                    # Remove noisy tracking params
                    for noisy_key in ["__dyn", "__csr", "__hsdp", "__hblp", "__sjsp"]:
                        base_form.pop(noisy_key, None)
        except Exception as e:
            logger.debug(f"[GroupCrawler] Error fetching base feed form from DB: {e}")

        # 2. Inject stable defaults if missing
        feed_form = base_form.copy()
        feed_form["fb_api_req_friendly_name"] = "GroupsCometFeedRegularStoriesPaginationQuery"
        feed_form["doc_id"] = feed_form.get("doc_id") or "38367899859521393"
        feed_form["fb_api_caller_class"] = "RelayModern"
        feed_form["server_timestamps"] = "true"
        feed_form["__comet_req"] = "15"
        feed_form["__a"] = "1"

        # 3. Inject fresh session tokens
        fresh_fb_dtsg = tenant_cookie.get("fb_dtsg") or IN_MEMORY_COOKIES.get("fb_dtsg") or feed_form.get("fb_dtsg")
        fresh_lsd = tenant_cookie.get("lsd") or IN_MEMORY_COOKIES.get("lsd") or feed_form.get("lsd")
        if fresh_fb_dtsg:
            feed_form["fb_dtsg"] = fresh_fb_dtsg
            feed_form["jazoest"] = "2" + str(sum(ord(c) for c in fresh_fb_dtsg))
        if fresh_lsd:
            feed_form["lsd"] = fresh_lsd

        user_id = tenant_cookie.get("user_id") or IN_MEMORY_COOKIES.get("user_id")
        if not user_id and raw_cookie:
            m = re.search(r'c_user=([^;]+)', raw_cookie)
            if m:
                user_id = m.group(1)
        if user_id:
            feed_form["__user"] = user_id
            feed_form["av"] = user_id

        fresh_sd = tenant_cookie.get("sd") or IN_MEMORY_COOKIES.get("sd")
        if fresh_sd and isinstance(fresh_sd, dict):
            if fresh_sd.get("rev"):
                feed_form["__rev"] = fresh_sd["rev"]
            if fresh_sd.get("hsi"):
                feed_form["__hsi"] = fresh_sd["hsi"]
            if fresh_sd.get("spin_r"):
                feed_form["__spin_r"] = fresh_sd["spin_r"]
            if fresh_sd.get("spin_b"):
                feed_form["__spin_b"] = fresh_sd["spin_b"]
            if fresh_sd.get("spin_t"):
                feed_form["__spin_t"] = fresh_sd["spin_t"]

        # 4. Inject variables
        existing_vars = {}
        if "variables" in base_form:
            try:
                existing_vars = json.loads(base_form["variables"])
            except Exception:
                pass

        merged_vars = DEFAULT_FEED_VARIABLES.copy()
        merged_vars.update(existing_vars)
        merged_vars["id"] = group_id or "0"
        merged_vars["sortingSetting"] = "CHRONOLOGICAL"
        if not merged_vars.get("count"):
            merged_vars["count"] = 3
        feed_form["variables"] = json.dumps(merged_vars, separators=(",", ":"))

        # 5. Build synthetic headers
        feed_headers = base_headers.copy()
        if not feed_headers.get("user-agent"):
            feed_headers["user-agent"] = tenant_cookie.get("user_agent") or IN_MEMORY_COOKIES.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        feed_headers["content-type"] = "application/x-www-form-urlencoded"
        feed_headers["origin"] = "https://www.facebook.com"
        if group_id:
            feed_headers["referer"] = f"https://www.facebook.com/groups/{group_id}"
        feed_headers["x-fb-friendly-name"] = "GroupsCometFeedRegularStoriesPaginationQuery"
        if raw_cookie:
            feed_headers["cookie"] = raw_cookie

        tpl = {
            "headers": feed_headers,
            "form_data": feed_form,
        }

        # Only cache if we have minimum valid credentials
        if fresh_fb_dtsg or raw_cookie or user_id:
            tenant_tpls = TENANT_TEMPLATES.setdefault(client_id, {})
            tenant_tpls["feed"] = tpl
            IN_MEMORY_TEMPLATES["feed"] = tpl
            logger.info(f"[GroupCrawler] Synthesized feed template for group '{group_id}' (client_id='{client_id}')")
            return tpl

        return None
