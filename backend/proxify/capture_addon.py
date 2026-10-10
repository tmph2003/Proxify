"""mitmproxy addon that captures all HTTP/HTTPS traffic and stores it."""

import functools
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from mitmproxy import http

from proxify.utils.content import is_text_content as _is_text_content

logger = logging.getLogger("proxify")

DEFAULT_IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3"
}

DEFAULT_IGNORE_DOMAINS = {
    "events.data.microsoft.com",
    "exp-tas.com",
    "google-analytics.com",
    "doubleclick.net"
}

CONFIG_FILE = Path(os.getenv("PROXIFY_CONFIG", "config.json"))

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "ignore_extensions": set(data.get("ignore_extensions", DEFAULT_IGNORE_EXTENSIONS)),
                    "ignore_domains": set(data.get("ignore_domains", DEFAULT_IGNORE_DOMAINS))
                }
        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            
    return {
        "ignore_extensions": DEFAULT_IGNORE_EXTENSIONS,
        "ignore_domains": DEFAULT_IGNORE_DOMAINS
    }

config_cache = load_config()
IGNORE_EXTENSIONS = config_cache["ignore_extensions"]
IGNORE_EXTENSIONS_TUPLE = tuple(IGNORE_EXTENSIONS)
IGNORE_DOMAINS = config_cache["ignore_domains"]




class CaptureAddon:
    """mitmproxy addon that intercepts requests/responses and saves them."""

    def __init__(
        self,
        storage,
        broadcast_fn: Optional[Callable] = None,
        is_db_enabled_fn: Optional[Callable[[], bool]] = None,
        domain_filter: Optional[list[str]] = None,
    ):
        """
        Args:
            storage: RequestStorage instance
            broadcast_fn: synchronous callback(summary_dict) to broadcast new requests
                          to dashboard. Called from the mitmproxy thread — the callback
                          is responsible for cross-thread scheduling.
            is_db_enabled_fn: callback to check if DB integration is enabled
            domain_filter: optional list of domains to capture (None = capture all)
        """
        self.storage = storage
        self._broadcast_fn = broadcast_fn
        self._is_db_enabled_fn = is_db_enabled_fn
        self.domain_filter = domain_filter
        

        
        # Load all registered plugins
        from proxify.plugins.registry import get_all_plugin_classes
        self.plugins = []
        for name, cls in get_all_plugin_classes().items():
            try:
                self.plugins.append(cls(storage=self.storage, config={}))
                logger.info(f"Loaded plugin: {name}")
            except Exception as e:
                logger.error(f"Failed to load plugin {name}: {e}", exc_info=True)

        self._get_matching_plugins = functools.lru_cache(maxsize=1024)(self._get_matching_plugins_impl)

    def _get_matching_plugins_impl(self, domain: str):
        """Yield plugins that match the given domain."""
        matches = []
        for plugin in self.plugins:
            # If target_domains is empty, it runs for all domains
            if not getattr(plugin, 'target_domains', []):
                matches.append(plugin)
                continue
            
            # If domain matches any of the target domains
            if any(t in domain for t in plugin.target_domains):
                matches.append(plugin)
        return tuple(matches)

    async def request(self, flow: http.HTTPFlow):
        """Intercept request and pass to plugins."""
        domain = flow.request.pretty_host
        
        # Execute matching plugins
        for plugin in self._get_matching_plugins(domain):
            try:
                await plugin.on_request(flow)
            except Exception as e:
                logger.error(f"Plugin {plugin.name} error on request: {e}", exc_info=True)
        
        if flow.error or flow.metadata.get("ad_blocked"):
            return

    async def responseheaders(self, flow: http.HTTPFlow):
        """Intercept response headers before the body is received.
        Use this to stream large static files without buffering them in RAM.
        """
        if flow.error or flow.metadata.get("ad_blocked"):
            return

        parsed = urlparse(flow.request.pretty_url)
        path = parsed.path or ""
        
        # If it's a static extension, stream it to save RAM
        # BUT: skip streaming for Zalo .js files — the Zalo plugin needs
        # to read and modify these files to inject JS hooks.
        if path.lower().endswith(IGNORE_EXTENSIONS_TUPLE):
            domain = flow.request.pretty_host
            if path.lower().endswith(".js") and "zalo" in domain:
                return  # Don't stream — let Zalo plugin modify the JS
            flow.response.stream = True
            return

    async def response(self, flow: http.HTTPFlow):
        """Capture completed request/response pair and pass to plugins."""
        try:
            domain = flow.request.pretty_host
            
            # Execute matching plugins
            for plugin in self._get_matching_plugins(domain):
                try:
                    await plugin.on_response(flow)
                except Exception as e:
                    logger.error(f"Plugin {plugin.name} error on response: {e}", exc_info=True)
            
            if flow.error or flow.metadata.get("ad_blocked"):
                return

            parsed = urlparse(flow.request.pretty_url)

            # Determine whether DB save is allowed
            db_save = True
            if self._is_db_enabled_fn and not self._is_db_enabled_fn():
                db_save = False

            if db_save:
                allowed_domains = getattr(self.storage, 'db_allowed_domains', [])
                if allowed_domains:
                    domain = parsed.hostname or ""
                    if not any(d in domain for d in allowed_domains):
                        db_save = False

            # Ignore static assets by extension (fast C-level check)
            path = parsed.path or ""
            if path.lower().endswith(IGNORE_EXTENSIONS_TUPLE):
                return
                
            # Ignore preflight requests
            if flow.request.method == "OPTIONS":
                return

            # Publish the response captured event
            from proxify.core.events import bus
            bus.publish("response_captured", flow=flow, db_save=db_save)

        except Exception as e:
            logger.error(f"Error capturing response: {e}", exc_info=True)

    def error(self, flow: http.HTTPFlow):
        """Handle flow errors."""
        if flow.error:
            # Suppress error log if we intentionally killed it (Ad Blocker)
            if flow.metadata.get("ad_blocked"):
                return
            logger.warning(f"Flow error: {flow.request.pretty_url} - {flow.error.msg}")
