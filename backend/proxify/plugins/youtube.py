"""YouTube Plugin."""

from typing import Any
from mitmproxy import http
from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin
from proxify.utils.youtube_utils import is_youtube_ad_request, strip_youtube_ads

@register_plugin("youtube")
class YouTubePlugin(BasePlugin):
    name = "YouTube Enhancer"
    description = "Chặn quảng cáo và tracking trên YouTube"
    target_domains = [
        "youtube.com",
        "googlevideo.com",
        "youtubei",
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "adservice.google.com",
    ]
    
    async def on_request(self, flow: Any) -> None:
        """Block ads and tracking requests gracefully."""
        if not isinstance(flow, http.HTTPFlow):
            return

        domain = flow.request.pretty_host
        # Fast skip: only process YouTube and Google ad domains
        if not any(d in domain for d in self.target_domains):
            return

        url = flow.request.pretty_url
        
        if is_youtube_ad_request(url, domain):
            self.logger.info(f"🚫 [BLOCKED BY {self.name}] {flow.request.method} {url[:120]}")
            flow.metadata["ad_blocked"] = True
            # Gracefully respond with 204 No Content.
            # NEVER call flow.kill() because it tears down the underlying TCP connection
            # and breaks HTTP/2 multiplexed streams (causing net::ERR_HTTP2_PROTOCOL_ERROR).
            flow.response = http.Response.make(
                204,
                b"",
                [
                    (b"content-type", b"text/plain"),
                    (b"access-control-allow-origin", b"*"),
                ],
            )

    async def on_response(self, flow: Any) -> None:
        """Strip ads from YouTube watch/shorts HTML pages and Innertube API JSON responses."""
        if not isinstance(flow, http.HTTPFlow):
            return

        domain = flow.request.pretty_host
        if 'youtube.com' not in domain and 'youtubei' not in domain:
            return

        if not flow.response or not flow.response.content:
            return

        content_type = flow.response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/json" not in content_type:
            return

        path = flow.request.path.lower()
        is_watch_or_home = path.startswith(("/watch", "/shorts")) or path == "/" or path == ""
        is_api = "youtubei/v1" in path
        if not (is_watch_or_home or is_api):
            return

        try:
            body = flow.response.content.decode("utf-8")
        except (UnicodeDecodeError, Exception):
            return
            
        if not body:
            return
            
        modified, new_body = strip_youtube_ads(body)
        if modified:
            flow.response.content = new_body.encode("utf-8")
            self.logger.info(f"🔪 [AD STRIPPED] Modified YouTube response: {flow.request.method} {path[:60]}")

