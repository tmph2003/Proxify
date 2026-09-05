"""
Crawler Engine — Shared HTTP Infrastructure
============================================
Delegation target (ch36) for all Facebook crawlers.

Provides the common HTTP transport layer: safe request execution via
Extension Bridge with curl_cffi fallback, cookie resolution chain,
header building, cursor extraction, and circuit breaker gating.

Instantiated once per ``FacebookCrawler`` (Facade) and injected into
each domain crawler via Constructor Injection (ch35).
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
from proxify.utils.circuit_breaker import crawl_breaker
from proxify.platforms.facebook.stealth import (
    SessionStateManager,
)
from proxify.platforms.facebook.auth import (
    get_saved_tokens,
    TENANT_COOKIES,
    IN_MEMORY_COOKIES,
)

logger = logging.getLogger("proxify.facebook.crawlers.engine")

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"


# ─── Mock Response ───────────────────────────────────────────────────────

class MockResponse:
    """Mock response returned when Extension Bridge succeeds."""
    def __init__(self, data: dict):
        self.text = data.get("text", "")
        self.status_code = data.get("status_code", 200)
        self.is_blocked = False
        self.is_disconnected = False


class DisconnectedResponse:
    """Mock response returned when Extension Bridge is offline or errored."""
    def __init__(self):
        self.text = ""
        self.status_code = 503
        self.is_blocked = True
        self.is_disconnected = True


# ─── CrawlerEngine ───────────────────────────────────────────────────────

class CrawlerEngine:
    """Shared HTTP infrastructure — Delegation target (ch36).

    NOT an abstract class. This is a utility/service object that provides
    the common transport layer for all Facebook crawlers.

    Injected into domain crawlers (GroupCrawler, ProfileCrawler, etc.)
    via Constructor Injection (ch35).

    Args:
        facade: The ``FacebookCrawler`` Facade instance that owns shared
                mutable state (``_stop_flag``, ``crawl_state``, ``network_client``).
    """

    def __init__(self, facade) -> None:
        self.facade = facade

    # ── Safe Request (Bridge + curl_cffi Fallback) ───────────────────

    async def safe_request(self, method: str, url: str, **kwargs):
        """Execute request with dual-engine strategy:

        1. Extension Bridge (first-party inside user's active Facebook tab)
        2. Fallback to native curl_cffi (via GlobalNetworkClient / StealthSessionManager)

        This is a direct port of ``FacebookCrawler._safe_request``.
        """
        from proxify.platforms.facebook.bridge import bridge

        headers = kwargs.get("headers", {})
        data = kwargs.get("data")
        if isinstance(data, bytes):
            data_str = data.decode("utf-8", "ignore")
        else:
            data_str = data or ""

        result = None
        is_comment = kwargs.get("is_comment_crawl", False)
        bridge_timeout = 8 if is_comment else 65
        max_retries = 1 if is_comment else 2

        for attempt in range(max_retries):
            use_bridge = bridge.is_connected(client_id=self.facade.client_id, threshold=60.0)
            last_poll = bridge.client_last_poll.get(self.facade.client_id, 0.0)
            logger.debug(
                f"[Engine] Bridge check (client={self.facade.client_id}): "
                f"connected={use_bridge} (attempt {attempt+1}/{max_retries}, "
                f"last poll: {time.time() - last_poll:.1f}s ago, is_comment={is_comment})"
            )

            if use_bridge:
                try:
                    result = await bridge.execute_request(
                        url=url,
                        method=method,
                        headers=headers,
                        data=data_str,
                        timeout=bridge_timeout,
                        client_id=self.facade.client_id,
                    )
                    if result:
                        logger.debug(
                            f"[Engine] Bridge returned status={result.get('status_code')}, "
                            f"len={len(result.get('text', ''))}, "
                            f"in_tab={result.get('executed_in_tab')}, "
                            f"tab_url={result.get('tab_url')}, "
                            f"tab_err={result.get('tab_error')}"
                        )
                        if result.get("status_code") == 200 and result.get("status") != "error":
                            break
                except Exception as e:
                    logger.warning(f"[Engine] Bridge request exception (attempt {attempt+1}): {e}")

            # If attempt failed but extension is still actively polling, retry before aborting
            if attempt < max_retries - 1 and bridge.is_connected(client_id=self.facade.client_id, threshold=30.0):
                logger.info(f"[Engine] Bridge attempt {attempt+1} did not return 200. Retrying in 2s...")
                await asyncio.sleep(2)
                continue
            else:
                break

        # If Extension Bridge is offline, disconnected, or returns error code, handle appropriately
        bridge_failed = False
        if not result or result.get("status") == "error" or result.get("status_code") == 0:
            bridge_failed = True

        if bridge_failed:
            err_detail = result.get("tab_error") if result else None
            if not use_bridge:
                disconnect_reason = f"Chrome Extension (client='{self.facade.client_id}') chưa kết nối hoặc đã bị tắt"
            elif err_detail:
                disconnect_reason = f"Lỗi phản hồi Extension: {err_detail}"
            else:
                disconnect_reason = "Không nhận được phản hồi từ Chrome Extension"

            logger.warning(f"[Engine] {disconnect_reason}. Dừng cào an toàn để bảo vệ tài khoản Facebook tránh bị Logout.")
            if not is_comment:
                self.facade._stop_flag = True
            self.facade.crawl_state.update(
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
            return DisconnectedResponse()

        return MockResponse(result)

    # ── Cookie Resolution Chain ──────────────────────────────────────

    @staticmethod
    async def resolve_cookie(
        client_cookie: Optional[str],
        tokens: Optional[dict] = None,
        client_id: str = "default",
    ) -> str:
        """Resolve cookie string from available sources (priority chain).

        Priority:
        1. Template cookie (with xs= merged from client_cookie if needed)
        2. User-provided cookie (client_cookie)
        3. TENANT_COOKIES / IN_MEMORY_COOKIES
        4. Persistent DB config (fb_cookie)
        5. Latest intercepted Facebook cookie from requests table
        """
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
        if tpl_cookie and "xs=" not in tpl_cookie:
            target_tenant = TENANT_COOKIES.get(client_id, {})
            current_mem = client_cookie or target_tenant.get("cookie", "") or IN_MEMORY_COOKIES.get("cookie", "")
            if "xs=" in current_mem:
                xs_match = re.search(r'xs=([^;]+)', current_mem)
                if xs_match:
                    tpl_cookie = f"{tpl_cookie}; xs={xs_match.group(1)}"

        if tpl_cookie and "xs=" in tpl_cookie:
            logger.debug("[Engine] Using exact matching cookie from template (with xs)")
            return tpl_cookie

        # Highest priority: user provided cookie
        if client_cookie and ("c_user=" in client_cookie or "xs=" in client_cookie):
            logger.debug("[Engine] Using user-provided fallback cookie")
            return client_cookie.strip()

        if client_cookie:
            logger.debug("[Engine] Using user-provided cookie")
            return client_cookie.strip()

        if tpl_cookie:
            logger.debug("[Engine] Using template cookie")
            return tpl_cookie

        try:
            target_tenant = TENANT_COOKIES.get(client_id, {})
            mem_cookie = target_tenant.get("cookie") or IN_MEMORY_COOKIES.get("cookie", "")
            if mem_cookie:
                logger.debug(f"[Engine] Using TENANT_COOKIES/IN_MEMORY_COOKIES fallback for '{client_id}'")
                return mem_cookie.strip()
        except Exception:
            pass

        # Fallback to persistent DB config
        try:
            from proxify.platforms.facebook.database import fb_db
            db_cookie = fb_db.config.get("fb_cookie")
            if db_cookie and db_cookie != "[REDACTED]":
                logger.debug("[Engine] Using persistent fb_cookie from config DB")
                return db_cookie.strip()
        except Exception as e:
            logger.debug(f"[Engine] Error fetching cookie from config DB: {e}")

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
                    logger.debug("[Engine] Using latest intercepted Facebook cookie from requests table")
                    return row[0].strip()
        except Exception as e:
            logger.debug(f"[Engine] Error fetching cookie from requests table: {e}")

        logger.error("[Engine] No cookies found!")
        return ""

    # ── Static Helpers ───────────────────────────────────────────────

    @staticmethod
    def build_headers(feed_tpl: dict, cookie: str, group_id: str) -> dict:
        """Build request headers from template, fixing anti-detection issues."""
        headers = feed_tpl.get("headers", {}).copy()
        # Clean case-insensitive duplicates
        for k in list(headers.keys()):
            if k.lower() in ("cookie", "referer"):
                headers.pop(k, None)
        headers["X-Proxify-Crawler"] = "1"
        headers["cookie"] = cookie
        headers["referer"] = f"https://www.facebook.com/groups/{group_id}"

        # We are using impersonate=None in StealthSessionManager so we MUST keep the browser's User-Agent
        return headers

    @staticmethod
    def extract_cursor(resp_text: str) -> str:
        """Extract pagination cursor from GraphQL response."""
        match = re.search(r'"(?:end_)?cursor"\s*:\s*"([^"]+)"', resp_text)
        return match.group(1) if match else ""
