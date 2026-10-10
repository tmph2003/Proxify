"""ExtensionContext capability gateway for Proxify extensions."""

import asyncio
import logging
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
)
from aiohttp import web

from proxify.core.interfaces import IMutatorInterceptor, IObserverInterceptor

logger = logging.getLogger("proxify.sdk.context")


class ExtensionContext:
    """
    Capability gateway exposed to extensions during `initialize()`.

    Decouples extension code from mitmproxy internals, aiohttp server setup,
    and PostgreSQL connection management.
    """

    def __init__(
        self,
        extension_id: str,
        router: Any,                      # ProxyRouter instance
        dashboard_app: web.Application,   # aiohttp web.Application
        db_manager: Any,                  # DatabaseManager (asyncpg pool)
        sync_db_pool: Any,                # DatabasePool (psycopg2 pool)
        worker: Any,                       # BackgroundWorker
        filter_instance: Optional[Any] = None, # PollingEndpointFilter
        event_bus: Optional[Any] = None,
        storage: Optional[Any] = None,
    ) -> None:
        self.extension_id = extension_id
        self._router = router
        self._app = dashboard_app
        self._db_manager = db_manager
        self._sync_pool = sync_db_pool
        self._worker = worker
        self._filter = filter_instance
        self._event_bus = event_bus
        self._storage = storage

        # Track registered items for diagnostics and lifecycle cleanup
        self._registered_routes: List[web.RouteDef] = []
        self._db_initializers: List[Callable[[], Coroutine[Any, Any, None]]] = []
        self._ui_pages: List[Dict[str, Any]] = []

    # ─── Property Accessors for Contract Compatibility ─────────────────────

    @property
    def app(self) -> web.Application:
        return self._app

    @property
    def router(self) -> Any:
        return self._router

    @property
    def worker(self) -> Any:
        return self._worker

    @property
    def event_bus(self) -> Any:
        return self._event_bus

    @property
    def storage(self) -> Any:
        return self._storage

    # ─── 1. Traffic Interception ───────────────────────────────────────────

    def register_observer(
        self,
        observer: IObserverInterceptor,
        domains: Optional[Iterable[str]] = None,
    ) -> None:
        """
        Register a non-blocking traffic observer.

        Observers run asynchronously in the background and must NOT mutate the flow.
        If `domains` is provided, it configures or overrides `observer.target_domains`.
        """
        if domains is not None:
            observer.target_domains = set(domains)
        self._router.register_observer(observer)
        logger.debug(f"[{self.extension_id}] Registered observer: {observer.__class__.__name__}")

    def register_mutator(
        self,
        mutator: IMutatorInterceptor,
        domains: Optional[Iterable[str]] = None,
    ) -> None:
        """
        Register a blocking traffic mutator.

        Mutators are awaited sequentially in the proxy pipeline and can modify
        request/response headers and bodies, or short-circuit responses.
        """
        if domains is not None:
            mutator.target_domains = set(domains)
        self._router.register_mutator(mutator)
        logger.debug(f"[{self.extension_id}] Registered mutator: {mutator.__class__.__name__}")

    def register_stream_domains(self, domains: Iterable[str]) -> None:
        """
        Register domain substrings whose responses must be streamed directly.

        Streaming bypasses mitmproxy's in-memory buffering, preventing high RAM usage
        for video, large binaries, or chunked media.
        """
        domain_list = list(domains)
        self._router.register_stream_domains(domain_list)
        logger.debug(f"[{self.extension_id}] Registered stream domains: {domain_list}")

    def register_ignored_hosts(self, hosts: Iterable[str]) -> None:
        """
        Register hosts that should pass through the proxy completely unintercepted.
        """
        host_list = list(hosts)
        for host in host_list:
            self._router.add_ignored_host(host)
        logger.debug(f"[{self.extension_id}] Registered ignored hosts: {host_list}")

    # ─── 2. HTTP Route Registration ────────────────────────────────────────

    def register_route(self, method: str, path: str, handler: Callable) -> None:
        """
        Register a single aiohttp HTTP endpoint.

        Parameters:
            method: HTTP verb ('GET', 'POST', 'PATCH', 'DELETE', etc.)
            path: Absolute URL path (e.g. '/api/myext/jobs')
            handler: aiohttp request handler callable
        """
        route_def = web.route(method.upper(), path, handler)
        self._registered_routes.append(route_def)
        self._app.router.add_route(method.upper(), path, handler)
        logger.debug(f"[{self.extension_id}] Registered route: {method.upper()} {path}")

    def register_routes(self, routes: List[web.RouteDef]) -> None:
        """
        Register a batch of aiohttp routes.
        """
        for r in routes:
            self._registered_routes.append(r)
        self._app.add_routes(routes)
        logger.debug(f"[{self.extension_id}] Registered {len(routes)} routes.")

    def register_polling_path(self, path: str) -> None:
        """
        Register a path that polls frequently to suppress redundant 200/304 access logs.
        """
        if self._filter and hasattr(self._filter, "add_ignored_path"):
            self._filter.add_ignored_path(path)

    # ─── 3. CQRS Topic Handlers ─────────────────────────────────────────────

    def register_topic_handler(
        self,
        topic: str,
        handler: Callable[[Dict[str, Any], Any], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register an asynchronous consumer for events in `core.raw_payloads` matching `topic`.

        Signature:
            async def handler(payload: dict, conn: asyncpg.Connection) -> None
        """
        self._worker.register_topic_handler(topic, handler)
        logger.debug(f"[{self.extension_id}] Registered CQRS topic handler for: {topic}")

    # Alias for flexibility
    register_payload_consumer = register_topic_handler

    # ─── 4. Database Schema Initializers & Pools ────────────────────────────

    def get_sync_db_pool(self) -> Any:
        """Return the shared psycopg2 ThreadedConnectionPool for synchronous operations."""
        return self._sync_pool

    def get_async_db_pool(self) -> Any:
        """Return the shared asyncpg Connection Pool for asynchronous operations."""
        return self._db_manager.pool

    def register_db_initializer(
        self,
        init_fn: Callable[[], Coroutine[Any, Any, None] | None],
    ) -> None:
        """
        Register a database schema initialization callable to be executed on startup.
        Supports both sync functions and async coroutines.
        """
        self._db_initializers.append(init_fn)

    # ─── 5. UI Integration Metadata ─────────────────────────────────────────

    def register_ui_page(
        self,
        title: str,
        path: str,
        icon: str = "",
        order: int = 100,
    ) -> None:
        """
        Register UI navigation metadata exposed via GET /api/extensions.

        Parameters:
            title: Human-readable page title for sidebar/topbar.
            path: Relative URL route (e.g. '/my-ext').
            icon: SVG string or icon identifier.
            order: Menu display sort order.
        """
        self._ui_pages.append({
            "name": self.extension_id,
            "title": title,
            "path": "/" + path.lstrip("/"),
            "icon": icon,
            "order": order,
        })
