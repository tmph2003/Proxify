from typing import Protocol, Set, List, Any
import asyncio
from mitmproxy import http

class EventListener(Protocol):
    """Protocol cho một Event Listener."""
    def __call__(self, *args: Any, **kwargs: Any) -> None:
        ...

class IObserverInterceptor(Protocol):
    """Read-only interceptor. Executed in the background. Must not mutate the flow."""
    target_domains: Set[str]
    
    async def handle_request(self, flow: http.HTTPFlow) -> None:
        pass
        
    async def handle_responseheaders(self, flow: http.HTTPFlow) -> None:
        pass
        
    async def handle_response(self, flow: http.HTTPFlow) -> None:
        pass

class IMutatorInterceptor(Protocol):
    """Mutating interceptor. Blocks the proxy pipeline. Can modify requests/responses."""
    target_domains: Set[str]
    
    async def handle_request(self, flow: http.HTTPFlow) -> None:
        pass
        
    async def handle_responseheaders(self, flow: http.HTTPFlow) -> None:
        pass
        
    async def handle_response(self, flow: http.HTTPFlow) -> None:
        pass

class IPlatformHandler(Protocol):
    """Defines a platform feature slice."""
    
    def get_observers(self) -> List[IObserverInterceptor]:
        return []
        
    def get_mutators(self) -> List[IMutatorInterceptor]:
        return []
