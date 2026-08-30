"""
Unified Stealth Engine for Proxify
====================================
Centralizes all anti-bot-detection logic: TLS fingerprint spoofing,
header consistency, session management, retry with backoff, and
soft-block detection.

Usage:
    from proxify.utils.stealth import StealthSessionManager

    manager = StealthSessionManager()
    session = await manager.get_session()  # AsyncSession with impersonation
    resp = await manager.request("GET", url, headers=headers)
"""

import asyncio
import logging
import os
import random
from typing import Optional, Dict

from curl_cffi.requests import AsyncSession

logger = logging.getLogger("proxify.stealth")

# ─── Configuration via Environment Variables ────────────────────────────────

# Which browser to impersonate. "chrome" = rolling latest.
# Override with specific version like "chrome131" if needed.
DEFAULT_IMPERSONATE = os.getenv("STEALTH_IMPERSONATE", "chrome")

# Max retries for transient failures (429, 503, connection errors)
MAX_RETRIES = int(os.getenv("STEALTH_MAX_RETRIES", "3"))

# Base delay in seconds for exponential backoff
BASE_DELAY = float(os.getenv("STEALTH_BASE_DELAY", "2.0"))

# Request timeout in seconds
REQUEST_TIMEOUT = float(os.getenv("STEALTH_TIMEOUT", "30.0"))

# ─── Soft-Block Detection Patterns ─────────────────────────────────────────

# If response body contains any of these, the site is returning a challenge
# instead of real content (200 OK but actually blocked)
SOFT_BLOCK_SIGNATURES = [
    b"checkpoint",
    b"captcha",
    b"_Spin_r",  # Facebook challenge redirect
    b'"require":["ServerRedirect"',  # Facebook server-side redirect to checkpoint
    b"Please verify you are a human",
    b"Access denied",
    b"challenge-platform",       # Cloudflare
    b"cf-mitigated: challenge",  # Cloudflare header
    b"Just a moment",            # Cloudflare waiting page
]

# ─── Headers that should be REMOVED before sending via curl_cffi ────────────
# curl_cffi handles these automatically based on the impersonate target.
# Manually setting them creates fingerprint inconsistencies.
HEADERS_TO_STRIP = frozenset([
    "host",
    "content-length",
    "accept-encoding",
    "connection",
    "transfer-encoding",
    # HTTP/2 pseudo-headers (mitmproxy preserves these)
    ":authority",
    ":method",
    ":path",
    ":scheme",
    # ─── Anti-detection: headers curl_cffi auto-generates correctly ──────
    # These are set by the impersonate engine based on the target browser.
    # Manually setting them (especially with HeadlessChrome values from
    # Playwright) is the #1 cause of bot detection.
    "sec-ch-ua",
    "sec-ch-ua-full-version-list",
    "sec-ch-ua-mobile",
    "sec-ch-ua-model",
    "sec-ch-ua-platform",
    "sec-ch-ua-platform-version",
    "sec-ch-prefers-color-scheme",
    # ─── Anti-detection: metadata headers that reveal automation ─────────
    "x-fb-friendly-name",   # Reveals exact GraphQL query name
    "x-asbd-id",            # Internal tracking ID
    "x-fb-lsd",             # Redundant — already in form_data as 'lsd'
])


def sanitize_headers(raw_headers: dict) -> dict:
    """Strip headers that curl_cffi should auto-generate for consistency.

    Removes pseudo-headers, hop-by-hop headers, sec-ch-ua* headers
    (which may contain HeadlessChrome fingerprint from Playwright),
    and automation-revealing metadata headers.
    """
    cleaned = {}
    for k, v in raw_headers.items():
        k_lower = k.lower()
        if k_lower in HEADERS_TO_STRIP:
            continue
        # Don't include headers that start with ':'
        if k_lower.startswith(":"):
            continue
        cleaned[k] = v
    return cleaned


def is_soft_blocked(status_code: int, content: bytes, headers: dict, url: str = "") -> bool:
    """Detect if a response is a soft block (200 OK but actually a challenge page).

    Many anti-bot systems return HTTP 200 with a challenge page instead of
    a traditional 403/429 to avoid detection by simple status code checks.
    """
    # Skip checking static assets from CDNs
    if "fbcdn.net" in url:
        return False
    # Check for Cloudflare challenge header
    cf_mitigated = headers.get("cf-mitigated", "")
    if "challenge" in cf_mitigated.lower():
        return True

    # Check for challenge page content
    # Only check HTML or JSON responses (skip JS/CSS static assets)
    content_type = headers.get("content-type", "").lower()
    if content and len(content) < 50000:  # Only check small responses
        if "text/html" in content_type or "application/json" in content_type:
            for sig in SOFT_BLOCK_SIGNATURES:
                if sig in content:
                    return True

    return False


def is_retryable_status(status_code: int) -> bool:
    """Check if the status code indicates a retryable error."""
    return status_code in (429, 503, 502, 520, 521, 522, 523, 524)

class AccountCheckpointError(Exception):
    """Raised when Facebook returns a checkpoint/challenge page."""
    pass

class ProxyBlockedError(Exception):
    """Raised when a proxy is blocked or failing repeatedly."""
    pass

class StealthSessionManager:
    """Manages curl_cffi AsyncSession instances with impersonation.

    Features:
    - Rolling latest Chrome impersonation by default
    - Automatic header sanitization
    - Exponential backoff with jitter on rate limits
    - Soft-block detection
    - Session reuse for connection efficiency
    - Thread-safe lazy initialization
    """

    def __init__(
        self,
        impersonate: str = DEFAULT_IMPERSONATE,
        max_retries: int = MAX_RETRIES,
        base_delay: float = BASE_DELAY,
        timeout: float = REQUEST_TIMEOUT,
        verify: bool = False,
    ):
        self._impersonate = impersonate
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._timeout = timeout
        self._verify = verify
        self._session: Optional[AsyncSession] = None
        self._lock: Optional[asyncio.Lock] = None
        self._request_count = 0
        self._block_count = 0
        self._current_proxy: Optional[str] = None
        self._current_cookies: Optional[Dict] = None
        self._base_headers: Dict = {}

        logger.info(
            f"🛡️ Stealth Engine initialized: impersonate={impersonate}, "
            f"max_retries={max_retries}, timeout={timeout}s"
        )

    def set_identity(self, proxy: Optional[str], cookies: Optional[Dict], user_agent: Optional[str] = None):
        """Set the identity (proxy, cookies, UA) for this session manager.
        This forces a session rotation on the next request.
        """
        self._current_proxy = proxy
        self._current_cookies = cookies
        if user_agent:
            self._base_headers["User-Agent"] = user_agent
        
        # Invalidate current session to force recreation with new identity
        if self._session:
            asyncio.create_task(self.close())
            self._session = None

    async def get_session(self) -> AsyncSession:
        """Get or create an AsyncSession with impersonation.

        The session is lazily created and reused for all requests
        to maintain connection pools and cookie state.
        """
        if self._session is None:
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                if self._session is None:
                    # Apply session-wide configurations
                    proxies = {"http": self._current_proxy, "https": self._current_proxy} if self._current_proxy else None
                    self._session = AsyncSession(
                        impersonate=self._impersonate,
                        verify=self._verify,
                        timeout=self._timeout,
                        proxies=proxies,
                        cookies=self._current_cookies,
                    )
                    logger.info(
                        f"🔒 Stealth session created (impersonate={self._impersonate}, proxy={'Yes' if proxies else 'No'})"
                    )
        return self._session

    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[dict] = None,
        data: Optional[bytes] = None,
        cookies: Optional[dict] = None,
        allow_redirects: bool = False,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None,
        extra_curl_options: Optional[dict] = None,
    ) -> "StealthResponse":
        """Send a request with stealth impersonation, retry logic, and soft-block detection.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Target URL
            headers: Request headers (will be sanitized automatically)
            data: Request body
            cookies: Optional cookies to merge
            allow_redirects: Whether to follow redirects
            timeout: Override default timeout
            proxy: Optional proxy URL
            extra_curl_options: Additional curl options

        Returns:
            StealthResponse with status, content, headers, and metadata
        """
        session = await self.get_session()

        # Merge base headers and sanitize
        raw_headers = self._base_headers.copy()
        if headers:
            raw_headers.update(headers)
            
        clean_headers = sanitize_headers(raw_headers)
        
        # Dynamically adjust Sec-Ch-Ua and Sec-Ch-Ua-Platform if User-Agent is provided
        # This prevents Checkpoint triggers when impersonate is Mac/Chrome150 but UA is Windows/Chrome152
        ua = clean_headers.get("User-Agent", "")
        if ua:
            import re
            m = re.search(r"Chrome/(\d+)", ua)
            if m:
                version = m.group(1)
                clean_headers["Sec-Ch-Ua"] = f'"Chromium";v="{version}", "Google Chrome";v="{version}", "Not;A=Brand";v="99"'
                
            if "Windows" in ua:
                clean_headers["Sec-Ch-Ua-Platform"] = '"Windows"'
                clean_headers["Sec-Ch-Ua-Mobile"] = "?0"
            elif "Macintosh" in ua:
                clean_headers["Sec-Ch-Ua-Platform"] = '"macOS"'
                clean_headers["Sec-Ch-Ua-Mobile"] = "?0"
            elif "Android" in ua:
                clean_headers["Sec-Ch-Ua-Platform"] = '"Android"'
                clean_headers["Sec-Ch-Ua-Mobile"] = "?1"

        effective_timeout = timeout or self._timeout

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                # Merge explicitly provided cookies with session cookies
                req_cookies = self._current_cookies.copy() if self._current_cookies else {}
                if cookies:
                    req_cookies.update(cookies)
                    
                # Use current proxy if explicitly provided proxy is None
                effective_proxy = proxy if proxy is not None else self._current_proxy

                kwargs = {
                    "method": method,
                    "url": url,
                    "headers": clean_headers,
                    "data": data,
                    "cookies": req_cookies,
                    "allow_redirects": allow_redirects,
                    "timeout": effective_timeout,
                    "proxy": effective_proxy,
                    **(extra_curl_options or {}),
                }

                logger.info(f"Stealth request ATTEMPT {attempt+1}: {method} {url}")
                import time
                t0 = time.time()
                
                resp = await session.request(**kwargs)
                
                logger.info(f"Stealth request SUCCESS: {method} {url} in {time.time()-t0:.2f}s (status={resp.status_code}, len={len(resp.content)})")
                try:
                    snippet = resp.text[:200].replace('\n', ' ')
                    logger.info(f"Response snippet: {snippet}")
                except Exception:
                    pass

                self._request_count += 1

                resp_headers = dict(resp.headers)

                # Check for soft blocks
                if is_soft_blocked(resp.status_code, resp.content, resp_headers, url):
                    self._block_count += 1
                    logger.warning(
                        f"⚠️ Soft block detected on attempt {attempt + 1}/{self._max_retries + 1}: "
                        f"{method} {url[:80]}... (status={resp.status_code}, "
                        f"total blocks={self._block_count})"
                    )
                    if attempt < self._max_retries:
                        delay = self._calculate_backoff(attempt)
                        logger.info(f"⏳ Backing off {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)
                        continue
                    # Final attempt still blocked - Raise Checkpoint exception for Queues to handle
                    raise AccountCheckpointError(f"Account hit checkpoint/soft-block on {method} {url[:80]}")

                # Check for retryable HTTP errors
                if is_retryable_status(resp.status_code):
                    logger.warning(
                        f"⚠️ Retryable status {resp.status_code} on attempt "
                        f"{attempt + 1}/{self._max_retries + 1}: {method} {url[:80]}..."
                    )
                    if attempt < self._max_retries:
                        # Check for Retry-After header
                        retry_after = resp_headers.get("retry-after")
                        if retry_after:
                            try:
                                delay = min(float(retry_after), 60.0)
                            except ValueError:
                                delay = self._calculate_backoff(attempt)
                        else:
                            delay = self._calculate_backoff(attempt)
                        logger.info(f"⏳ Backing off {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)
                        continue

                # Success
                return StealthResponse(
                    status_code=resp.status_code,
                    content=resp.content,
                    headers=resp_headers,
                    is_blocked=False,
                    attempts=attempt + 1,
                )

            except Exception as e:
                last_error = e
                logger.error(
                    f"❌ Request error on attempt {attempt + 1}/{self._max_retries + 1}: "
                    f"{method} {url[:80]}... — {e}"
                )
                if attempt < self._max_retries:
                    delay = self._calculate_backoff(attempt)
                    await asyncio.sleep(delay)
                    continue

        # All retries exhausted
        # Check if proxy error
        if last_error and "proxy" in str(last_error).lower():
             raise ProxyBlockedError(f"Proxy failed after {self._max_retries + 1} attempts: {last_error}")
             
        raise StealthRequestError(
            f"All {self._max_retries + 1} attempts failed for {method} {url[:80]}",
            last_error=last_error,
        )

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter.

        Formula: base_delay * 2^attempt + random jitter (0-1s)
        Capped at 60 seconds.
        """
        delay = self._base_delay * (2 ** attempt)
        jitter = random.uniform(0, 1.0)
        return min(delay + jitter, 60.0)

    @property
    def stats(self) -> dict:
        """Return stealth engine statistics."""
        return {
            "impersonate": self._impersonate,
            "total_requests": self._request_count,
            "total_blocks": self._block_count,
            "block_rate": (
                f"{(self._block_count / self._request_count * 100):.1f}%"
                if self._request_count > 0
                else "N/A"
            ),
            "session_active": self._session is not None,
        }

    async def close(self):
        """Close the underlying session."""
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
            logger.info("🔓 Stealth session closed.")

    async def verify_fingerprint(self) -> dict:
        """Verify the current TLS fingerprint against a known test service.

        Returns a dict with JA3 hash, HTTP/2 fingerprint, and other metadata
        that can be compared against real Chrome browser values.
        """
        session = await self.get_session()
        try:
            resp = await session.get(
                "https://tls.browserleaks.com/json",
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    f"🔍 Fingerprint check: JA3={data.get('ja3_hash', 'N/A')}, "
                    f"Protocol={data.get('protocol', 'N/A')}, "
                    f"User-Agent={data.get('user_agent', 'N/A')[:60]}"
                )
                return data
        except Exception as e:
            logger.error(f"Fingerprint verification failed: {e}")
        return {}


class StealthResponse:
    """Wrapper around a curl_cffi response with additional metadata."""

    __slots__ = ("status_code", "content", "headers", "is_blocked", "attempts")

    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict,
        is_blocked: bool = False,
        attempts: int = 1,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers
        self.is_blocked = is_blocked
        self.attempts = attempts

    @property
    def text(self) -> str:
        """Decode content as UTF-8 text."""
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("utf-8", errors="replace")

    def __repr__(self):
        blocked = " [BLOCKED]" if self.is_blocked else ""
        return f"<StealthResponse {self.status_code}{blocked} ({len(self.content)} bytes, {self.attempts} attempts)>"


class StealthRequestError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, message: str, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.last_error = last_error
