import asyncio
import logging
from typing import Dict, List, Set, Optional, Tuple
from urllib.parse import urlparse
from mitmproxy import http
from proxify.core.interfaces import IObserverInterceptor, IMutatorInterceptor

logger = logging.getLogger("proxify.core.router")

# Static extensions that should be streamed directly to the browser
# instead of being buffered in mitmproxy's RAM.
# Buffering these adds latency (store-and-forward) and wastes memory.
_STREAM_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".wav", ".ogg", ".webm", ".avi", ".mkv", ".flv",
    ".map",  # source maps
)

# Content-types that are safe to stream (no plugin ever modifies these)
_STREAM_CONTENT_TYPES = ("image/", "font/", "application/font", "application/x-font")

# Domains whose responses should ALWAYS be streamed (video CDNs, etc.)
# These domains serve large binary data that must never be buffered.
_STREAM_DOMAINS = (
    "googlevideo.com",
    "tiktokcdn.com",
    "byteoversea.com",
    "ibyteimg.com",
)

class TrieNode:
    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}
        self.observers: List[IObserverInterceptor] = []
        self.mutators: List[IMutatorInterceptor] = []

class ProxyRouter:
    """
    O(depth) Radix Trie Router for matching domains (including wildcards/subdomains).
    Domains are inserted in reverse order (e.g., com -> facebook -> api).
    """
    def __init__(self, ignored_hosts: Optional[List[str]] = None):
        self.root = TrieNode()
        self.global_observers: List[IObserverInterceptor] = []
        self.global_mutators: List[IMutatorInterceptor] = []
        self.ignored_hosts: List[str] = [h.strip().lower() for h in (ignored_hosts or []) if h.strip()]

    def is_ignored(self, host: str) -> bool:
        if not host or not self.ignored_hosts:
            return False
        host_lower = host.lower()
        return any(h in host_lower for h in self.ignored_hosts)

    def _insert(self, domain: str, interceptor, is_mutator: bool):
        if not domain:
            return
        
        parts = domain.lower().strip('.').split('.')
        parts.reverse() # com -> facebook -> api
        
        curr = self.root
        for part in parts:
            if part not in curr.children:
                curr.children[part] = TrieNode()
            curr = curr.children[part]
            
        if is_mutator:
            curr.mutators.append(interceptor)
        else:
            curr.observers.append(interceptor)

    def register_observer(self, observer: IObserverInterceptor):
        if not observer.target_domains:
            self.global_observers.append(observer)
            return
        for domain in observer.target_domains:
            self._insert(domain, observer, False)

    def register_mutator(self, mutator: IMutatorInterceptor):
        if not mutator.target_domains:
            self.global_mutators.append(mutator)
            return
        for domain in mutator.target_domains:
            self._insert(domain, mutator, True)

    def _search(self, domain: str) -> Tuple[List[IObserverInterceptor], List[IMutatorInterceptor]]:
        """Finds all interceptors matching the domain and its parent domains."""
        parts = domain.lower().strip('.').split('.')
        parts.reverse()
        
        matched_observers = list(self.global_observers)
        matched_mutators = list(self.global_mutators)
        
        curr = self.root
        for part in parts:
            if part in curr.children:
                curr = curr.children[part]
                matched_observers.extend(curr.observers)
                matched_mutators.extend(curr.mutators)
            else:
                break
                
        return matched_observers, matched_mutators

    async def route_request(self, flow: http.HTTPFlow) -> None:
        """Route request to appropriate interceptors."""
        host = flow.request.pretty_host
        if self.is_ignored(host):
            return
        observers, mutators = self._search(host)
        
        # 1. Fire and forget observers
        for obs in observers:
            # We must NOT pass the raw flow if it's going to outlive the proxy pipeline.
            # But asyncio.create_task on the same loop usually runs synchronously until the first await,
            # which might be safe if observers just extract data synchronously and then await IO.
            # For strict safety, observers must extract data synchronously in handle_request before yielding.
            asyncio.create_task(obs.handle_request(flow))
            
        # 2. Await mutators sequentially
        for mut in mutators:
            await mut.handle_request(flow)

    async def route_responseheaders(self, flow: http.HTTPFlow) -> None:
        """Route response headers to appropriate interceptors. Useful for stream bypassing."""
        content_type = flow.response.headers.get("content-type", "").lower()

        # 1. Stream large media by content-type (OOM protection)
        if "video/" in content_type or "audio/" in content_type:
            flow.response.stream = True
            return

        # 2. Stream oversized responses (OOM protection)
        content_length = int(flow.response.headers.get("content-length", 0))
        if content_length > 5 * 1024 * 1024:  # > 5MB
            flow.response.stream = True
            return

        # 3. Stream static assets by content-type (images, fonts)
        #    No plugin ever modifies these — buffering them only adds latency.
        if any(content_type.startswith(ct) for ct in _STREAM_CONTENT_TYPES):
            flow.response.stream = True
            return

        # 4. Stream static assets by URL extension (images, fonts, source maps, media)
        #    NOTE: .css and .js are intentionally EXCLUDED because mutator plugins
        #    (e.g., ZaloPlugin) may need to read and modify the response body.
        path = urlparse(flow.request.pretty_url).path.lower()
        if path.endswith(_STREAM_EXTENSIONS):
            flow.response.stream = True
            return

        # 5. Stream known video CDN domains unconditionally
        #    googlevideo.com serves YouTube video chunks with content-type
        #    "application/octet-stream" and chunked transfer encoding (no content-length).
        #    This bypasses both the video/ content-type check and the >5MB size check.
        #    Without streaming, mitmproxy buffers the entire video in RAM → hang.
        host = flow.request.pretty_host
        if any(d in host for d in _STREAM_DOMAINS):
            flow.response.stream = True
            return

        if self.is_ignored(host):
            return
        observers, mutators = self._search(host)
        
        for obs in observers:
            if hasattr(obs, 'handle_responseheaders'):
                asyncio.create_task(obs.handle_responseheaders(flow))
            
        for mut in mutators:
            if hasattr(mut, 'handle_responseheaders'):
                await mut.handle_responseheaders(flow)


    async def route_response(self, flow: http.HTTPFlow) -> None:
        """Route response to appropriate interceptors."""
        host = flow.request.pretty_host
        if self.is_ignored(host):
            return
        observers, mutators = self._search(host)
        
        for obs in observers:
            asyncio.create_task(obs.handle_response(flow))
            
        for mut in mutators:
            await mut.handle_response(flow)
