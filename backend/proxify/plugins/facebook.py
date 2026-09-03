"""Facebook Plugin Adapter (Structural Pattern: Adapter / Bridge).

Adapts the modern FacebookPlatform subsystem (backend/proxify/platforms/facebook/)
into the legacy BasePlugin interface for backwards-compatibility and registry discovery.
Reference: Python Design Patterns (Chapter 9: Adapter Pattern).
"""

from typing import Any, List, Dict
from aiohttp import web
import logging

from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin
from proxify.platforms.facebook.api import FacebookAPI
from proxify.platforms.facebook.interceptor import FacebookGraphQLObserver
from proxify.database import pool as db_pool

logger = logging.getLogger("proxify.plugin.facebook")


@register_plugin("facebook")
class FacebookPlugin(BasePlugin):
    """
    Adapter bridging BasePlugin to the domain-driven FacebookPlatform modules.
    Eliminates duplicated API routes and interceptor logic.
    """
    name = "Facebook Extractor"
    description = "Trích xuất bài viết, bình luận từ Facebook GraphQL (Adapter tới FacebookPlatform)"
    target_domains = ["facebook.com", "fbcdn.net"]

    def __init__(self, storage=None, config=None):
        super().__init__(storage, config)
        self._api = FacebookAPI(db_pool=db_pool)
        self._observer = FacebookGraphQLObserver()

    async def on_request(self, flow: Any) -> None:
        """Delegate request interception to FacebookGraphQLObserver."""
        await self._observer.handle_request(flow)

    async def on_response(self, flow: Any) -> None:
        """Delegate response interception to FacebookGraphQLObserver."""
        await self._observer.handle_response(flow)

    def get_api_routes(self) -> List[web.RouteDef]:
        """Delegate route definitions to FacebookAPI."""
        return self._api.get_api_routes()

    def get_ui_tabs(self) -> List[Dict[str, str]]:
        return [
            {
                "id": "facebook",
                "title": "Facebook",
                "url": "/facebook",
                "icon": "facebook"
            }
        ]
