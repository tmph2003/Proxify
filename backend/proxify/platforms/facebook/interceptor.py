import json
import logging
from pathlib import Path
from mitmproxy import http
from proxify.core.interfaces import IObserverInterceptor
from proxify.core.eventbus import AsyncEventBus

logger = logging.getLogger("proxify.facebook.interceptor")

class FacebookGraphQLObserver(IObserverInterceptor):
    """
    Read-only interceptor for Facebook traffic.
    Captures GraphQL tokens and detecting inactive posts.
    Runs asynchronously in the background.
    """
    target_domains = {"facebook.com", "fbcdn.net"}
    
    def __init__(self, event_bus: AsyncEventBus = None):
        self.event_bus = event_bus

    async def handle_request(self, flow: http.HTTPFlow) -> None:
        """Capture GraphQL tokens."""
        # Because this is a background task, we must extract data quickly.
        path = flow.request.path
        if "/api/graphql" not in path:
            return
            
        form_data_raw = flow.request.urlencoded_form
        if not form_data_raw:
            return
            
        form_data = dict(form_data_raw)
        variables_str = form_data.get("variables", "")
        if not variables_str:
            return
            
        if "x-proxify-crawler" in flow.request.headers:
            return
            
        if "fb_dtsg" in form_data:
            friendly_name = form_data.get("fb_api_req_friendly_name", "")
            
            headers = {}
            for k, v in flow.request.headers.items(multi=True):
                k_lower = k.lower()
                if k_lower == 'cookie':
                    headers['cookie'] = headers.get('cookie', '') + ('; ' + v if headers.get('cookie') else v)
                else:
                    headers[k_lower] = v
                    
            headers.pop("content-length", None)
            headers.pop("accept-encoding", None)
            
            payload = {
                "friendly_name": friendly_name,
                "headers": headers,
                "form_data": form_data
            }
            # Publish to EventBus for background processing instead of parsing JSON synchronously
            if self.event_bus:
                self.event_bus.publish("facebook.graphql.request", payload)

    async def handle_response(self, flow: http.HTTPFlow) -> None:
        """Capture GraphQL responses and detect inactive posts."""
        path = flow.request.path
        
        # 1. Capture GraphQL Responses (DISABLED)
        # Passive ingestion disabled: Chỉ lưu bài viết khi người dùng chủ động cào qua Dashboard/Crawler.
        # Tránh việc người dùng lướt Newsfeed, Reels hoặc nhóm khác bị tự động lưu bài lạ vào DB.
        pass
        
        # 2. Detect inactive posts
        if flow.request.method == "GET" and "/groups/" in path and "/posts/" in path:
            body = flow.response.get_text(strict=False) or ""
            is_error = "B\\u1ea1n hi\\u1ec7n kh\\u00f4ng xem \\u0111\\u01b0\\u1ee3c n\\u1ed9i dung n\\u00e0y" in body
            if is_error:
                # Publish event instead of blocking the DB
                payload = {
                    "path": flow.request.path,
                    "is_active": False
                }
                if self.event_bus:
                    self.event_bus.publish("facebook.post.status", payload)
