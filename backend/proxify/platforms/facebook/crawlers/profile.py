"""
Profile Crawler — Facebook Personal Profile Timeline (Hardened Security Architecture)
=====================================================================================
Domain crawler for Facebook personal profile timeline.

Pattern: **Delegation (ch36)** — ``ProfileCrawler`` HAS-A ``CrawlerEngine``
(injected via Constructor Injection ch35).

Security Rules (Zero Checkpoint Architecture):
1. **Zero Cookie Transmission in Backend**: Never send user cookies from Python/Docker curl_cffi.
2. **Mandatory Extension Bridge Execution**: All authenticated GraphQL requests MUST run
   inside the user's real Chrome browser tab via Extension Bridge.
3. **Anonymous-Only Slug Resolution**: Resolving vanity URLs fetches public HTML without any cookies.
4. **Instant Circuit Breaking**: If any checkpoint or session invalidation signal is detected,
   the crawler aborts immediately to protect user accounts.
5. **Human-like Gaussian Delay**: Uses natural pacing (2.0s - 8.0s) between timeline pages.
"""

import asyncio
import json
import logging
import re
import time
import urllib.parse
from typing import Optional

from proxify.database import pool as shared_pool
from proxify.utils.stealth import StealthRequestError
from proxify.platforms.facebook.stealth import (
    SessionStateManager,
    page_delay,
)
from proxify.platforms.facebook.auth import (
    get_saved_tokens,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
    IN_MEMORY_COOKIES,
)
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper

logger = logging.getLogger("proxify.facebook.crawlers.profile")

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"
MAX_PAGES_PER_SESSION = 500


# ─── Profile Locked & Checkpoint Detection ───────────────────────────

class ProfileLockError(Exception):
    """Raised when a Facebook profile is locked, private, or unavailable."""

    def __init__(self, profile_id: str, reason: str = ""):
        self.profile_id = profile_id
        self.reason = reason
        super().__init__(f"Profile {profile_id} is locked/private: {reason}")


def _is_profile_locked(html: str) -> bool:
    """Detect if a Facebook profile page indicates locked/private/unavailable."""
    if not html:
        return False
    lock_indicators = [
        "Trang này không có sẵn",
        "This Page Isn't Available",
        "This content isn't available",
        "Bạn hiện không xem được nội dung này",
        "The link you followed may be broken",
        "Nội dung này hiện không có sẵn",
        "Tài khoản đã bị khóa",
        "This account has been locked",
        '"is_profile_translucent":true',
    ]
    for indicator in lock_indicators:
        if indicator in html:
            return True
    return False


def _is_checkpoint_detected(resp_text: str) -> bool:
    """Detect if Facebook returned a security checkpoint or session interruption."""
    if not resp_text:
        return False
    checkpoint_indicators = [
        "/checkpoint/",
        "checkpoint/?next",
        '"is_checkpoint":true',
        "checkpoint_required",
        "login.php?next",
        "Tài khoản của bạn đã bị khóa",
        "Your account has been locked",
    ]
    for ind in checkpoint_indicators:
        if ind in resp_text:
            return True
    return False


# ─── Default GraphQL Variables ───────────────────────────────────────

DEFAULT_PROFILE_FEED_VARIABLES = {
    "count": 5,
    "cursor": None,
    "feedbackSource": 0,
    "feedLocation": "TIMELINE",
    "omitPinnedPost": False,
    "privacySelectorRenderLocation": "COMET_STREAM",
    "renderLocation": "timeline",
    "scale": 1,
    "trackingCode": None,
    "__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider": True,
    "__relay_internal__pv__GHLShouldChangeSponsoredDataFieldNamerelayprovider": True,
    "__relay_internal__pv__CometFeedStory_enable_reactor_facepilerelayprovider": False,
    "__relay_internal__pv__CometFeedStory_enable_social_context_sentence_in_aggregationsrelayprovider": False,
    "__relay_internal__pv__CometUFIShareActionMigrationrelayprovider": True,
    "__relay_internal__pv__StoriesShouldEnablePhotosensitiveContentWarningrelayprovider": False,
    "__relay_internal__pv__ShouldEnableBakedInTextStoriesrelayprovider": False,
    "__relay_internal__pv__StoriesShouldIncludeFbNotesrelayprovider": True,
}


# ─── Resolve Profile ID (Strictly Anonymous — No Cookies) ───────────

async def resolve_profile_id(profile_id_or_url: str) -> tuple[str, Optional[str]]:
    """Resolve a Facebook profile identifier to numeric User ID.

    Accepts:
    - Numeric ID: ``100012345678``
    - Vanity URL: ``johndoe`` or ``profile.php?id=100012345678``
    - Full URL: ``https://www.facebook.com/johndoe``

    SECURITY RULE:
    - If already numeric, NO network request is made.
    - If vanity URL, fetches public HTML strictly as a guest WITHOUT ANY COOKIE.
      Never uses logged-in user cookies from backend.
    """
    raw = profile_id_or_url.strip().rstrip("/")

    # Strip full URL prefix
    for prefix in [
        "https://www.facebook.com/",
        "http://www.facebook.com/",
        "https://facebook.com/",
        "http://facebook.com/",
        "https://m.facebook.com/",
    ]:
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
            break

    # 1. Direct profile.php?id=XXXXX -> No request needed
    m = re.search(r"profile\.php\?id=(\d+)", raw)
    if m:
        return m.group(1), None

    # 2. Already numeric -> No request needed
    if raw.isdigit():
        return raw, None

    # 3. Vanity slug -> Resolve via pure anonymous guest GET (NO COOKIE)
    slug = raw.split("?")[0].split("/")[0]
    if not slug:
        raise ProfileLockError(profile_id_or_url, "empty_slug")

    try:
        from curl_cffi.requests import AsyncSession

        ua = IN_MEMORY_COOKIES.get("user_agent") or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        # Strictly NO COOKIE header here!
        headers = {
            "user-agent": ua,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "vi,en;q=0.9",
        }

        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(f"https://www.facebook.com/{slug}", headers=headers, timeout=12)
            html = resp.text or ""

            if _is_profile_locked(html):
                raise ProfileLockError(slug, "locked_or_unavailable")

            user_id = _extract_user_id_from_html(html)
            display_name = _extract_display_name_from_html(html)
            if user_id:
                logger.info(
                    f"[ProfileCrawler] Resolved slug '{slug}' -> User ID '{user_id}', name='{display_name}'"
                )
                return user_id, display_name

    except ProfileLockError:
        raise
    except Exception as e:
        logger.warning(f"[ProfileCrawler] Error resolving profile '{slug}': {e}")

    return slug, None


def _extract_user_id_from_html(html: str) -> Optional[str]:
    """Extract numeric user ID from profile page HTML."""
    patterns = [
        r'"userID":"(\d+)"',
        r'"ownerID":"(\d+)"',
        r'"profileID":"(\d+)"',
        r'"actorID":"(\d+)"',
        r'"user_id":"(\d+)"',
        r'content="fb://profile/(\d+)"',
        r'"entity_id":"(\d+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _extract_display_name_from_html(html: str) -> Optional[str]:
    """Extract display name from profile page HTML."""
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if m:
        name = m.group(1).strip()
        for suffix in [" | Facebook", " - Facebook", " — Facebook"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()
        if name and name != "Facebook":
            return name
    return None


# ─── ProfileCrawler ─────────────────────────────────────────────────

class ProfileCrawler:
    """Facebook personal profile timeline crawler — Delegation target (ch36).

    HAS-A ``CrawlerEngine`` (composition, NOT inheritance).
    Injected via Constructor Injection (ch35).

    All requests execute exclusively via Extension Bridge inside the active Chrome tab.
    """

    def __init__(self, engine) -> None:
        self.engine = engine

    # ── Synthesize Profile Feed Template ─────────────────────────────

    def synthesize_profile_feed_template(
        self,
        user_id: str,
        client_id: str = "default",
    ) -> Optional[dict]:
        """Generate a synthetic profile timeline feed template.

        Uses ``ProfileCometTimelineFeedQuery`` (doc_id: 27920308094306621).
        Executed In-Tab by Extension Bridge; cookies and headers are handled natively by Chrome.
        """
        tokens = TENANT_TEMPLATES.get(client_id) or IN_MEMORY_TEMPLATES
        feed_tpl = tokens.get("feed") if isinstance(tokens, dict) else None

        base_form = {}
        base_headers = {}

        if feed_tpl and isinstance(feed_tpl, dict):
            base_form = feed_tpl.get("form_data", {}).copy()
            base_headers = feed_tpl.get("headers", {}).copy()

        if not base_form:
            try:
                with shared_pool.cursor() as cur:
                    cur.execute("""
                        SELECT request_body, request_headers::jsonb
                        FROM requests
                        WHERE url LIKE '%facebook.com/api/graphql%'
                          AND request_body LIKE '%fb_dtsg=%'
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
                        for noisy_key in ["__dyn", "__csr", "__hsdp", "__hblp", "__sjsp"]:
                            base_form.pop(noisy_key, None)
            except Exception as e:
                logger.debug(f"[ProfileCrawler] Error fetching base_form from DB: {e}")

        if not base_form:
            logger.warning("[ProfileCrawler] Cannot synthesize profile template — no base form available")
            return None

        # Build form data for ProfileCometTimelineFeedQuery
        profile_form = base_form.copy()
        profile_form["fb_api_req_friendly_name"] = "ProfileCometTimelineFeedQuery"
        profile_form["doc_id"] = "27920308094306621"
        profile_form["fb_api_caller_class"] = "RelayModern"
        profile_form["server_timestamps"] = "true"
        profile_form["__comet_req"] = "15"
        profile_form["__a"] = "1"
        profile_form["__crn"] = "comet.fbweb.CometProfileTimelineListViewRoute"

        variables = DEFAULT_PROFILE_FEED_VARIABLES.copy()
        variables["userID"] = user_id
        profile_form["variables"] = json.dumps(variables, separators=(",", ":"))

        # Build headers
        profile_headers = base_headers.copy()
        profile_headers["Content-Type"] = "application/x-www-form-urlencoded"
        profile_headers["X-FB-Friendly-Name"] = "ProfileCometTimelineFeedQuery"
        profile_headers["Origin"] = "https://www.facebook.com"
        profile_headers["Referer"] = f"https://www.facebook.com/profile.php?id={user_id}"
        profile_headers["Sec-Fetch-Dest"] = "empty"
        profile_headers["Sec-Fetch-Mode"] = "cors"
        profile_headers["Sec-Fetch-Site"] = "same-origin"

        return {
            "headers": profile_headers,
            "form_data": profile_form,
        }

    # ── Execute Profile Timeline Crawl ───────────────────────────────

    async def execute_crawl_profile_feed(
        self,
        profile_id: str,
        start_timestamp: int,
        end_timestamp: int,
        template: Optional[dict] = None,
        client_cookie: Optional[str] = None,
    ) -> None:
        """Crawl a Facebook user's timeline posts strictly via Extension Bridge."""
        facade = self.engine.facade
        crawl_state = facade.crawl_state
        session_state = facade._session_state
        client_id = facade.client_id

        crawl_state.update(
            status="running",
            group_id=profile_id,
            message=f"🔍 Đang kiểm tra trang cá nhân {profile_id}...",
            total_posts=0,
            total_comments=0,
            updated_at=time.time(),
        )

        # ── Step 1: Strict Extension Bridge Connectivity Guard ───────
        from proxify.platforms.facebook.bridge import bridge
        if not bridge.is_connected(client_id=client_id, threshold=60.0):
            logger.warning(f"[ProfileCrawler] Chrome Extension offline for client '{client_id}'. Refusing to crawl.")
            facade._stop_flag = True
            crawl_state.update(
                status="error",
                message=(
                    "⚠️ Chrome Extension chưa kết nối hoặc chưa mở tab Facebook!\n\n"
                    "🛡️ NGUYÊN TẮC BẢO VỆ AN TOÀN TÀI KHOẢN:\n"
                    "Hệ thống yêu cầu bắt buộc chạy In-Tab qua Extension trình duyệt thật\n"
                    "để chống Checkpoint từ Facebook.\n\n"
                    "👉 Vui lòng mở Chrome có cài Proxify Extension, mở sẵn một tab Facebook và bấm cào lại!"
                ),
                updated_at=time.time(),
            )
            return

        # ── Step 2: Resolve numeric user ID (Anonymous — No Cookies) ─
        try:
            user_id, display_name = await resolve_profile_id(profile_id)
        except ProfileLockError as e:
            crawl_state.update(
                status="error",
                message=f"🔒 Trang cá nhân bị khóa hoặc riêng tư: {e.reason}",
                updated_at=time.time(),
            )
            return

        profile_label = display_name or user_id
        crawl_state.update(
            message=f"👤 Đang thu thập bài viết: {profile_label} (qua Chrome Extension)",
            updated_at=time.time(),
        )

        # ── Step 3: Synthesize profile feed template ─────────────────
        feed_tpl = self.synthesize_profile_feed_template(user_id, client_id=client_id)
        if not feed_tpl:
            crawl_state.update(
                status="error",
                message="⚠️ Chưa có mẫu gói tin Facebook. Vui lòng mở Facebook trên trình duyệt lướt vài bài để bắt đầu.",
                updated_at=time.time(),
            )
            return

        # ── Step 4: Pagination loop via Extension Bridge ─────────────
        cursor = None
        page_idx = 0
        total_posts = 0
        total_comments = 0
        consecutive_empty = 0
        detected_name = display_name

        while page_idx < MAX_PAGES_PER_SESSION:
            if facade._stop_flag:
                crawl_state.update(
                    status="idle",
                    message=f"⛔ Đã dừng. Thu thập được {total_posts} bài viết từ {profile_label}.",
                    updated_at=time.time(),
                )
                return

            page_idx += 1

            # Update variables with cursor
            try:
                form_data = feed_tpl.get("form_data", {}).copy()
                session_state.update_params(form_data)
                variables = json.loads(form_data.get("variables", "{}"))
                variables["userID"] = user_id
                variables["cursor"] = cursor
                form_data["variables"] = json.dumps(variables, separators=(",", ":"))
                form_data["__req"] = hex(page_idx)[2:]
            except Exception as e:
                logger.error(f"[ProfileCrawler] Error setting variables: {e}")
                break

            headers = feed_tpl.get("headers", {}).copy()
            headers["X-Proxify-Crawler"] = "1"

            crawl_state["message"] = (
                f"📄 Đang tải trang {page_idx} — {profile_label} "
                f"({total_posts} bài viết)"
            )
            crawl_state["updated_at"] = time.time()

            try:
                resp = await self.engine.safe_request(
                    "POST",
                    GRAPHQL_ENDPOINT,
                    headers=headers,
                    data=urllib.parse.urlencode(form_data).encode(),
                )
            except StealthRequestError as e:
                logger.error(f"[ProfileCrawler] Request failed at page {page_idx}: {e}")
                crawl_state.update(
                    status="error",
                    message=f"❌ Lỗi request trang {page_idx}: {e}",
                    updated_at=time.time(),
                )
                return

            resp_text = resp.text
            if not resp_text or resp.is_blocked:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    logger.warning("[ProfileCrawler] 3 consecutive empty/blocked responses. Stopping.")
                    break
                await asyncio.sleep(page_delay(facade.delay_config))
                continue

            consecutive_empty = 0

            # ── Checkpoint & Lock Circuit Breaker ────────────────────
            if _is_checkpoint_detected(resp_text):
                logger.critical(f"[ProfileCrawler] Checkpoint detected on profile {profile_label}! Emergency abort.")
                facade._stop_flag = True
                crawl_state.update(
                    status="error",
                    message=(
                        f"🚨 Phát hiện tín hiệu Checkpoint hoặc phiên xác minh từ Facebook!\n"
                        f"Hệ thống đã NGẮT TOÀN BỘ TIẾN TRÌNH CÀO NGAY LẬP TỨC để bảo vệ an toàn tài khoản của bạn."
                    ),
                    updated_at=time.time(),
                )
                return

            if _is_profile_locked(resp_text):
                crawl_state.update(
                    status="error",
                    message=f"🔒 Trang cá nhân {profile_label} bị khóa hoặc riêng tư.",
                    updated_at=time.time(),
                )
                return

            # ── Extract posts (skip group filtering) ─────────────────
            p_count, c_count, det_name = extract_from_responses(
                [resp_text],
                {},
                group_id=None,
                group_name=None,
                start_ts=start_timestamp if start_timestamp else None,
                end_ts=end_timestamp if end_timestamp else None,
                post_id=None,
                group_numeric_id=None,
            )

            if det_name:
                detected_name = det_name

            total_posts += p_count
            total_comments += c_count

            crawl_state["total_posts"] = total_posts
            crawl_state["total_comments"] = total_comments

            # Check for old posts — if creation_time < start_timestamp, stop
            if start_timestamp and p_count > 0:
                oldest_in_page = self._find_oldest_creation_time(resp_text)
                if oldest_in_page and oldest_in_page < start_timestamp:
                    logger.info(
                        f"[ProfileCrawler] Found post older than start_ts "
                        f"({oldest_in_page} < {start_timestamp}). Stopping."
                    )
                    break

            # ── Extract cursor for next page ─────────────────────────
            next_cursor = self._extract_profile_cursor(resp_text) or self.engine.extract_cursor(resp_text)
            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
                # Human-like pacing delay
                await asyncio.sleep(page_delay(facade.delay_config))
            else:
                logger.info("[ProfileCrawler] No more pages (cursor exhausted).")
                break

        # ── Done ─────────────────────────────────────────────────────
        crawl_state.update(
            status="idle",
            message=(
                f"✅ Hoàn tất thu thập trang cá nhân {profile_label}! "
                f"Tổng: {total_posts} bài viết, {total_comments} bình luận."
            ),
            updated_at=time.time(),
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_profile_cursor(resp_text: str) -> Optional[str]:
        """Extract pagination cursor specifically from timeline_list_feed_units page_info."""
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                page_infos = DataHelper.find_key(obj, "page_info")
                for pi in page_infos:
                    if isinstance(pi, dict) and pi.get("has_next_page"):
                        end_cur = pi.get("end_cursor")
                        if end_cur:
                            return end_cur
            except Exception:
                pass
        return None

    @staticmethod
    def _find_oldest_creation_time(resp_text: str) -> Optional[int]:
        """Find the oldest creation_time among Story nodes in a response."""
        oldest = None
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                stories = DataHelper.extract_nodes(obj, "Story")
                for story in stories:
                    c_times = DataHelper.find_key(story, "creation_time")
                    for ct in c_times:
                        if isinstance(ct, int):
                            if oldest is None or ct < oldest:
                                oldest = ct
            except Exception:
                pass
        return oldest
