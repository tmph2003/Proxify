"""
Stealth Upstream Addon for mitmproxy
=====================================
Intercepts HTTP requests and replays them using the Stealth Engine
(curl_cffi with browser TLS impersonation) to bypass anti-bot systems.

Activated via the --stealth CLI flag.
"""

import logging
from mitmproxy import http

from proxify.utils.stealth import (
    StealthSessionManager,
    StealthRequestError,
    sanitize_headers,
)

logger = logging.getLogger("proxify.stealth")


class StealthUpstreamAddon:
    """
    mitmproxy addon that replays requests through curl_cffi with
    Chrome TLS fingerprint impersonation.

    How it works:
    1. Intercept outgoing request in mitmproxy
    2. Strip mitmproxy-specific headers
    3. Replay the request via curl_cffi (which presents a real Chrome TLS fingerprint)
    4. Return the response back to mitmproxy → client
    """

    def __init__(self, target_domains=None):
        self.target_domains = target_domains
        self._manager = StealthSessionManager()

    async def request(self, flow: http.HTTPFlow):
        # Skip if another addon already set a response
        if flow.response:
            return

        # Don't spoof WebSocket upgrades
        if flow.request.headers.get("upgrade", "").lower() == "websocket":
            return

        # Crawler requests already use curl_cffi for TLS impersonation.
        # Let them pass through mitmproxy normally (still logged in UI)
        # to avoid double curl_cffi spoofing.
        if "x-proxify-crawler" in flow.request.headers:
            del flow.request.headers["x-proxify-crawler"]
            return

        # Filter by target domains if specified
        if self.target_domains:
            domain = flow.request.pretty_host
            if not any(d in domain for d in self.target_domains):
                return
                
        # Skip chat and real-time endpoints (curl_cffi buffers responses and breaks long-polling/streaming)
        domain = flow.request.pretty_host
        if "edge-chat" in domain or "mqtt" in domain:
            return
        # Don't spoof static assets or video streams
        url = flow.request.pretty_url
        url_lower = url.lower()
        if any(ext in url_lower for ext in [".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".webm", ".woff", ".ttf", "rsrc.php"]):
            return
        method = flow.request.method
        headers = dict(flow.request.headers)
        data = flow.request.raw_content

        try:
            resp = await self._manager.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                allow_redirects=False,
            )

            # Build mitmproxy response from stealth response
            response_headers = []
            for k, v in resp.headers.items():
                k_lower = k.lower()
                # Skip hop-by-hop headers that mitmproxy manages
                if k_lower in ("content-encoding", "content-length", "transfer-encoding"):
                    continue
                response_headers.append((k_lower.encode(), str(v).encode()))

            flow.response = http.Response.make(
                resp.status_code,
                resp.content,
                response_headers,
            )

            if resp.is_blocked:
                logger.warning(
                    f"⚠️ Stealth: Possibly blocked — {method} {url[:80]}... "
                    f"(status={resp.status_code}, attempts={resp.attempts})"
                )
            else:
                logger.info(f"🕵️ Stealth OK: {method} {resp.status_code} {url[:80]}...")

        except StealthRequestError as e:
            logger.error(f"❌ Stealth exhausted retries: {url[:80]}... — {e}")
            flow.response = http.Response.make(
                502,
                f"Stealth Proxy Error: {e}".encode("utf-8"),
                [(b"content-type", b"text/plain")],
            )
        except Exception as e:
            logger.error(f"❌ Stealth unexpected error: {url[:80]}... — {e}")
            flow.response = http.Response.make(
                502,
                f"Stealth Proxy Error: {e}".encode("utf-8"),
                [(b"content-type", b"text/plain")],
            )
