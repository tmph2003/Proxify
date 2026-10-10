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

# Domains whose responses should ALWAYS be streamed (video CDNs, static assets, etc.)
# These domains serve large binary data that must never be buffered.
_STREAM_DOMAINS = (
    "googlevideo.com",
    "tiktokcdn.com",
    "byteoversea.com",
    "ibyteimg.com",
    "fbcdn.net",
    "fbsbx.com",
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
        self.ignored_hosts: List[str] = [h.strip().lstrip("*.").split(":", 1)[0].lower() for h in (ignored_hosts or []) if h.strip()]
        self.stream_domains: Set[str] = {d.split(":", 1)[0].strip().lower() for d in _STREAM_DOMAINS}

    def register_stream_domains(self, domains) -> None:
        self.stream_domains.update(d.split(":", 1)[0].strip().lower() for d in domains if d)

    def add_ignored_host(self, host: str) -> None:
        clean = host.strip().lstrip("*.").split(":", 1)[0].lower() if host else ""
        if clean and clean not in self.ignored_hosts:
            self.ignored_hosts.append(clean)

    def is_ignored(self, host: Optional[str]) -> bool:
        if not host or not self.ignored_hosts:
            return False
        clean_host = host.split(":", 1)[0].strip().lower()
        if not clean_host:
            return False
        return any(clean_host == h or clean_host.endswith('.' + h) for h in self.ignored_hosts)

    def _insert(self, domain: str, interceptor, is_mutator: bool):
        if not domain:
            return
        
        clean_domain = domain.split(":", 1)[0].strip().lstrip("*.").lower()
        if not clean_domain:
            return

        parts = clean_domain.strip('.').split('.')
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

    def _search(self, domain: Optional[str]) -> Tuple[List[IObserverInterceptor], List[IMutatorInterceptor]]:
        """Finds all interceptors matching the domain and its parent domains."""
        matched_observers = list(self.global_observers)
        matched_mutators = list(self.global_mutators)
        if not domain:
            return matched_observers, matched_mutators

        clean_domain = domain.split(":", 1)[0].strip().lower()
        if not clean_domain:
            return matched_observers, matched_mutators

        parts = clean_domain.strip('.').split('.')
        parts.reverse()
        
        curr = self.root
        for part in parts:
            if part in curr.children:
                curr = curr.children[part]
                matched_observers.extend(curr.observers)
                matched_mutators.extend(curr.mutators)
            else:
                break
                
        # Deduplicate while preserving traversal order
        unique_observers = []
        seen_obs = set()
        for obs in matched_observers:
            if obs not in seen_obs:
                seen_obs.add(obs)
                unique_observers.append(obs)

        unique_mutators = []
        seen_mut = set()
        for mut in matched_mutators:
            if mut not in seen_mut:
                seen_mut.add(mut)
                unique_mutators.append(mut)

        return unique_observers, unique_mutators

    async def route_request(self, flow: http.HTTPFlow) -> None:
        """Route request to appropriate interceptors."""
        if not flow or not flow.request:
            return
        host = flow.request.pretty_host or ""
        if self.is_ignored(host):
            return
        observers, mutators = self._search(host)
        
        # 1. Fire and forget observers
        for obs in observers:
            async def _safe_obs_req(observer, f):
                try:
                    await observer.handle_request(f)
                except Exception as e:
                    logger.error(f"Observer error in handle_request for {host}: {e}", exc_info=True)
            asyncio.create_task(_safe_obs_req(obs, flow))
            
        # 2. Await mutators sequentially
        for mut in mutators:
            try:
                await mut.handle_request(flow)
            except Exception as e:
                logger.error(f"Mutator error in handle_request for {host}: {e}", exc_info=True)

    async def route_responseheaders(self, flow: http.HTTPFlow) -> None:
        """Route response headers to appropriate interceptors. Useful for stream bypassing."""
        if not flow or not flow.request or not flow.response:
            return

        content_type = flow.response.headers.get("content-type", "").lower()

        # 1. Stream large media by content-type (OOM protection)
        if "video/" in content_type or "audio/" in content_type:
            flow.response.stream = True
            return

        # 2. Stream oversized responses (OOM protection)
        try:
            content_length = int(flow.response.headers.get("content-length", 0))
        except (ValueError, TypeError):
            content_length = 0
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
        url = flow.request.pretty_url or ""
        path = urlparse(url).path.lower()
        if path.endswith(_STREAM_EXTENSIONS):
            flow.response.stream = True
            return

        # 5. Stream known video CDN domains unconditionally
        #    googlevideo.com serves YouTube video chunks with content-type
        #    "application/octet-stream" and chunked transfer encoding (no content-length).
        #    This bypasses both the video/ content-type check and the >5MB size check.
        #    Without streaming, mitmproxy buffers the entire video in RAM → hang.
        raw_host = flow.request.pretty_host or ""
        clean_host = raw_host.split(":", 1)[0].strip().lower()
        if any(clean_host == d or clean_host.endswith('.' + d) for d in self.stream_domains):
            flow.response.stream = True
            return

        if self.is_ignored(raw_host):
            return
        observers, mutators = self._search(raw_host)
        
        for obs in observers:
            if hasattr(obs, 'handle_responseheaders'):
                async def _safe_obs_headers(observer, f):
                    try:
                        await observer.handle_responseheaders(f)
                    except Exception as e:
                        logger.error(f"Observer error in handle_responseheaders for {raw_host}: {e}", exc_info=True)
                asyncio.create_task(_safe_obs_headers(obs, flow))
            
        for mut in mutators:
            if hasattr(mut, 'handle_responseheaders'):
                try:
                    await mut.handle_responseheaders(flow)
                except Exception as e:
                    logger.error(f"Mutator error in handle_responseheaders for {raw_host}: {e}", exc_info=True)


    async def route_response(self, flow: http.HTTPFlow) -> None:
        """Route response to appropriate interceptors."""
        if not flow or not flow.request or not flow.response:
            return
        host = flow.request.pretty_host or ""
        if self.is_ignored(host):
            return
        observers, mutators = self._search(host)
        
        for obs in observers:
            async def _safe_obs_resp(observer, f):
                try:
                    await observer.handle_response(f)
                except Exception as e:
                    logger.error(f"Observer error in handle_response for {host}: {e}", exc_info=True)
            asyncio.create_task(_safe_obs_resp(obs, flow))
            
        for mut in mutators:
            try:
                await mut.handle_response(flow)
            except Exception as e:
                logger.error(f"Mutator error in handle_response for {host}: {e}", exc_info=True)
