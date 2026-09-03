import asyncio
import logging
from typing import Dict, List, Set, Optional, Tuple
from mitmproxy import http
from proxify.core.interfaces import IObserverInterceptor, IMutatorInterceptor

logger = logging.getLogger("proxify.core.router")

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
        # Built-in OOM protection: automatically stream large media files
        content_type = flow.response.headers.get("content-type", "").lower()
        if "video/" in content_type or "audio/" in content_type:
            flow.response.stream = True
            return
            
        content_length = int(flow.response.headers.get("content-length", 0))
        if content_length > 5 * 1024 * 1024: # > 5MB
            flow.response.stream = True
            return

        host = flow.request.pretty_host
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
