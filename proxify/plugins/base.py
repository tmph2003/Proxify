"""Base architecture for Proxify plugins."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from aiohttp import web

logger = logging.getLogger("proxify.plugins")

class BasePlugin(ABC):
    """
    Base class for all Proxify plugins.
    Plugins can intercept network requests/responses and provide UI/API extensions.
    """

    # Plugin metadata
    name: str = "Unknown Plugin"
    description: str = ""
    version: str = "1.0.0"
    target_domains: List[str] = []  # Empty means match all domains (global plugin)

    def __init__(self, storage=None, config=None):
        """
        Initialize the plugin.
        :param storage: The central RequestStorage instance.
        :param config: Plugin-specific configuration dict.
        """
        self.storage = storage
        self.config = config or {}
        self.logger = logging.getLogger(f"proxify.plugin.{self.__class__.__name__}")

    async def on_request(self, flow: Any) -> None:
        """
        Called when a request is intercepted by mitmproxy.
        Can modify the flow or extract data.
        """
        pass

    async def on_response(self, flow: Any) -> None:
        """
        Called when a response is intercepted by mitmproxy.
        Can modify the flow or extract data.
        """
        pass

    # Aliases for V2 Router compatibility (IObserverInterceptor / IMutatorInterceptor)
    async def handle_request(self, flow: Any) -> None:
        return await self.on_request(flow)

    async def handle_response(self, flow: Any) -> None:
        return await self.on_response(flow)

    def get_api_routes(self) -> List[web.RouteDef]:
        """
        Return a list of aiohttp routes to be injected into the Dashboard API.
        Example: [web.get('/api/myplugin/stats', self.handle_stats)]
        """
        return []

    def get_ui_tabs(self) -> List[Dict[str, str]]:
        """
        Return a list of UI tabs to be added to the Dashboard.
        Format: [{"id": "myplugin", "label": "My Plugin", "html_path": "/path/to/myplugin.html"}]
        """
        return []
