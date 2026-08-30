from typing import List
from aiohttp import web
from proxify.core.interfaces import IPlatformHandler, IObserverInterceptor, IMutatorInterceptor
from proxify.core.eventbus import AsyncEventBus
from proxify.platforms.facebook.interceptor import FacebookGraphQLObserver
from proxify.platforms.facebook.api import FacebookAPI

class FacebookPlatform(IPlatformHandler):
    """
    Facebook Platform slice implementation.
    """
    def __init__(self, event_bus: AsyncEventBus):
        self.event_bus = event_bus
        self.observer = FacebookGraphQLObserver(event_bus)
        
        # Use the newly refactored API routes, passing asyncpg pool
        self.api = FacebookAPI(db_pool=event_bus.db_pool)

    def get_observers(self) -> List[IObserverInterceptor]:
        return [self.observer]
        
    def get_mutators(self) -> List[IMutatorInterceptor]:
        return []
        
    def get_api_routes(self) -> List[web.RouteDef]:
        return self.api.get_api_routes()
