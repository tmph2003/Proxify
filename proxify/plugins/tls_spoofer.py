"""TLS Spoofer Plugin — uses the unified Stealth Engine."""
import os
from typing import Any
from mitmproxy import http
from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin
from proxify.utils.stealth import (
    StealthSessionManager,
    StealthRequestError,
)


@register_plugin("tls_spoofer")
class TLSSpooferPlugin(BasePlugin):
    name = "TLS Spoofer (JA3 Bypass)"
    description = "Uses curl_cffi to impersonate Chrome TLS fingerprint for target domains"

    def __init__(self, storage=None, config=None):
        super().__init__(storage, config)

        env_domains = os.getenv(
            "SPOOF_DOMAINS",
            "tiktok.com,tiktokv.com,byteoversea.com,tiktokcdn.com",
        )
        self.target_domains = [d.strip() for d in env_domains.split(",") if d.strip()]

        # Use the unified stealth engine
        self._manager = StealthSessionManager()

    async def on_request(self, flow: Any) -> None:
        """Intercept the request and spoof it using the Stealth Engine."""
        if not isinstance(flow, http.HTTPFlow):
            return

        domain = flow.request.pretty_host

        # Only spoof requests directed to target domains
        if not any(d in domain for d in self.target_domains):
            return

        # Don't spoof WebSockets
        if (
            flow.request.headers.get("upgrade", "").lower() == "websocket"
            or getattr(flow, "websocket", None)
        ):
            return

        # Don't re-spoof our own crawler requests
        if "x-proxify-crawler" in flow.request.headers:
            return

        self.logger.info(
            f"🕵️ [TLS SPOOFER] Spoofing: {flow.request.url[:100]}..."
        )

        method = flow.request.method
        url = flow.request.url
        content = flow.request.content
        headers = dict(flow.request.headers)

        try:
            resp = await self._manager.request(
                method=method,
                url=url,
                headers=headers,
                data=content,
            )

            # Build mitmproxy-compatible response headers
            response_headers = []
            for k, v in resp.headers.items():
                k_lower = k.lower()
                if k_lower in ("content-encoding", "content-length", "transfer-encoding"):
                    continue
                response_headers.append((k_lower.encode(), str(v).encode()))

            flow.response = http.Response.make(
                resp.status_code,
                resp.content,
                response_headers,
            )

            if resp.is_blocked:
                self.logger.warning(
                    f"⚠️ [TLS SPOOFER] Possibly blocked: {resp.status_code} "
                    f"({len(resp.content)} bytes, {resp.attempts} attempts)"
                )
            else:
                self.logger.info(
                    f"✅ [TLS SPOOFER] Success: {resp.status_code} "
                    f"({len(resp.content)} bytes)"
                )

        except StealthRequestError as e:
            self.logger.error(f"❌ [TLS SPOOFER] All retries failed: {e}")
            flow.response = http.Response.make(
                502,
                f"TLS Spoofing Failed: {e}".encode(),
                [(b"content-type", b"text/plain")],
            )
        except Exception as e:
            self.logger.error(f"❌ [TLS SPOOFER] Unexpected error: {e}")
            flow.response = http.Response.make(
                502,
                f"TLS Spoofing Failed: {e}".encode(),
                [(b"content-type", b"text/plain")],
            )

    async def shutdown(self):
        await self._manager.close()
