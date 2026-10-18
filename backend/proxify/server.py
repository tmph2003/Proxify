import asyncio
import logging
import os
import socket
from pathlib import Path
from aiohttp import web
from mitmproxy.tools.dump import DumpMaster
from mitmproxy.options import Options

# Clean Architecture: Enforce IPv4-only address resolution at Application Transport Layer.
# By coercing AF_UNSPEC (0) to AF_INET, we prevent RFC 6724 IPv6 precedence from attempting
# unreachable IPv6 sockets in Docker Bridge (eliminating [Errno 101] Network unreachable
# and [Errno 99] Cannot assign requested address), while preserving host DNS forwarding and avoiding
# dangerous kernel-level sysctls or hardcoded public DNS servers.
_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    if family == socket.AF_UNSPEC or family == 0:
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, *args, **kwargs)

socket.getaddrinfo = _ipv4_only_getaddrinfo

from proxify.core.database import DatabaseManager
from proxify.core.eventbus import AsyncEventBus
from proxify.core.router import ProxyRouter
from proxify.core.worker import BackgroundWorker
from proxify.database import pool as sync_db_pool
from proxify.sdk.loader import ExtensionLoader

logger = logging.getLogger("proxify.server")

class PollingEndpointFilter(logging.Filter):
    """Filters out repetitive polling requests (200/304 OK) to keep console logs clean."""
    DEFAULT_IGNORED_PATHS = {
        "/api/stats",
        "/api/status",
        "/api/health",
        "/ws",
    }

    def __init__(self):
        super().__init__()
        self.ignored_paths = set(self.DEFAULT_IGNORED_PATHS)

    def add_ignored_path(self, path: str) -> None:
        self.ignored_paths.add(path)

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Suppress successful polling responses
        if " 200 " in msg or " 304 " in msg:
            for path in self.ignored_paths:
                if path in msg:
                    return False
        return True

polling_filter = PollingEndpointFilter()
logging.getLogger("aiohttp.access").addFilter(polling_filter)

class ProxyAddon:
    """The central Mitmproxy Addon that delegates to the fast Router."""
    def __init__(self, router: ProxyRouter):
        self.router = router

    async def request(self, flow):
        try:
            await self.router.route_request(flow)
        except Exception as e:
            logger.error(f"Error in ProxyAddon.request: {e}", exc_info=True)

    async def responseheaders(self, flow):
        try:
            if flow and flow.response and "alt-svc" in flow.response.headers:
                del flow.response.headers["alt-svc"]
            await self.router.route_responseheaders(flow)
        except Exception as e:
            logger.error(f"Error in ProxyAddon.responseheaders: {e}", exc_info=True)

    async def response(self, flow):
        try:
            if flow and flow.response and "alt-svc" in flow.response.headers:
                del flow.response.headers["alt-svc"]
            await self.router.route_response(flow)
        except Exception as e:
            logger.error(f"Error in ProxyAddon.response: {e}", exc_info=True)

class V1GlobalObserver:
    """Wraps V1 interceptors to bridge mitmproxy flows to the legacy Global Dashboard."""
    target_domains = [] # Listen to all domains
    
    def __init__(self, broadcast_fn, storage, ignored_hosts: list[str] = None, router: ProxyRouter = None):
        from proxify.core.listeners import DashboardBroadcaster, DatabaseWriter
        self.broadcaster = DashboardBroadcaster(broadcast_fn)
        self.db_writer = DatabaseWriter(storage)
        self.ignored_hosts = [h.strip().lower() for h in (ignored_hosts or []) if h.strip()]
        self.router = router
        
    async def handle_request(self, flow):
        pass
        
    async def handle_response(self, flow):
        if not flow or not flow.request or not flow.response:
            return
        if flow.metadata.get("ad_blocked"):
            return
        raw_host = flow.request.pretty_host or ""
        domain = raw_host.split(":", 1)[0].strip().lower()
        if any(
            domain == h 
            or domain.endswith('.' + h) 
            or (h.endswith('*') and domain.startswith(h.rstrip('*')))
            for h in self.ignored_hosts
        ):
            return

        # Skip requests matched by any registered record filter (e.g., streaming/telemetry noise)
        path = (flow.request.path or "").lower()
        url = flow.request.pretty_url or ""
        if self.router and self.router.should_skip_record(domain, path, url):
            return

        # Determine whether DB save is allowed based on V1 storage settings
        db_save = getattr(self.db_writer.storage, 'db_integration_enabled', False)
        if db_save:
            allowed_domains = getattr(self.db_writer.storage, 'db_allowed_domains', [])
            if allowed_domains:
                if not any(domain == d or domain.endswith('.' + d) for d in allowed_domains):
                    db_save = False

        self.broadcaster(flow, db_save=db_save)
        self.db_writer(flow, db_save=db_save)

async def start_dashboard(dashboard_instance, port=8888):
    runner = web.AppRunner(dashboard_instance.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Dashboard running on port {port}")
    return runner

async def run_server():
    """Single Event Loop Execution for Proxify v2"""
    # 1. Initialize Database
    dsn = os.getenv("DB_DSN", "postgresql://proxify_user:proxify_pass@localhost:5432/proxify_db")
    db_manager = DatabaseManager()
    await db_manager.connect(dsn)

    # 2. Initialize AsyncEventBus and Background Worker
    event_bus = AsyncEventBus(db_pool=db_manager.pool)
    event_bus.start()
    
    worker = BackgroundWorker(db_manager)
    worker.start()

    # 2.5 Universal Capture Scope: Intercept all web traffic by default (or restrict if INTERCEPT_DOMAINS is explicitly set)
    # High-bandwidth video CDNs and strict auth endpoints remain in explicit_bypasses for zero-latency streaming and login safety.
    import re

    custom_intercept = os.getenv("INTERCEPT_DOMAINS", "").strip()
    allow_patterns = []
    if custom_intercept:
        for d in custom_intercept.split(","):
            d = d.strip()
            if d:
                allow_patterns.append(rf'(?:^|\.){re.escape(d)}(?::|$)')

    # Explicit bypass safety net for high-bandwidth/auth domains that should never be TLS-intercepted:
    explicit_bypasses = [
        r'(?:^|\.)googlevideo\.com(?::|$)',
        r'(?:^|\.)c\.youtube\.com(?::|$)',
        r'(?:^|\.)accounts\.youtube\.com(?::|$)',
        r'(?:^|\.)signaler-pa\.youtube\.com(?::|$)',
        r'(?:^|\.)accounts\.google\.com(?::|$)',
        r'(?:^|\.)clients\d*\.google\.com(?::|$)',
        r'(?:^|\.)gvt[123]\.com(?::|$)',
    ]

    # Also parse IGNORE_HOSTS for Router application layer safety net (only essential background/CDN noise by default)
    raw_ignore = os.getenv(
        "IGNORE_HOSTS",
        "googlevideo.com,c.youtube.com,accounts.youtube.com,signaler-pa.youtube.com,accounts.google.com,clients6.google.com,client-channel.google.com,gvt1.com,gvt2.com,gvt3.com,1e100.net,nel.goog,msftncsi.com,windowsupdate.com",
    )
    ignored_hosts = [h.strip().lstrip("*.").split(":", 1)[0].lower() for h in raw_ignore.split(",") if h.strip()]
    if allow_patterns:
        logger.info(f"🛡️ Traffic Scope: allow_hosts restricted to {len(allow_patterns)} custom patterns.")
    else:
        logger.info("🌐 Traffic Scope: Universal Capture enabled across all domains (excluding video CDNs & auth bypasses).")

    # 3. Initialize Router
    router = ProxyRouter(ignored_hosts=ignored_hosts)

    # 4. Start Mitmproxy in the same event loop
    proxy_port = int(os.environ.get("PROXY_PORT", 8080))
    opts_kwargs = dict(
        listen_host="0.0.0.0",
        listen_port=proxy_port,
        ssl_insecure=True,
        http2=True,
        ignore_hosts=explicit_bypasses,
    )
    if allow_patterns:
        opts_kwargs["allow_hosts"] = allow_patterns
    opts = Options(**opts_kwargs)
    master = DumpMaster(opts, with_termlog=True, with_dumper=False)
    master.addons.add(ProxyAddon(router))

    # 4.5. Initialize V1 RequestStorage and Global Observer
    from proxify.core.traffic_storage import RequestStorage
    storage = RequestStorage()
    
    # 5. Initialize Dashboard instance
    dashboard_port = int(os.environ.get("DASHBOARD_PORT", 8888))
    from proxify.dashboard import Dashboard
    dashboard_instance = Dashboard(storage, port=dashboard_port)
    
    loop = asyncio.get_running_loop()
    def _deferred_broadcast(*args, **kwargs):
        if dashboard_instance:
            coro = dashboard_instance.broadcast(*args, **kwargs)
            try:
                asyncio.get_running_loop()
                asyncio.create_task(coro)
            except RuntimeError:
                # Called from a background thread (e.g., DatabaseWriter worker)
                asyncio.run_coroutine_threadsafe(coro, loop)
            
    from proxify.core.events import bus as v1_bus
    def on_db_row_created(req_uuid: str, row_id: int, **kwargs):
        _deferred_broadcast({"req_uuid": req_uuid, "row_id": row_id}, msg_type="update_id")
    v1_bus.subscribe("db_row_created", on_db_row_created)
            
    global_observer = V1GlobalObserver(_deferred_broadcast, storage, ignored_hosts=ignored_hosts, router=router)
    router.register_observer(global_observer)

    # 6. Discover and load modular extensions before runner setup (aiohttp routes freeze at setup)
    extension_loader = ExtensionLoader()
    await extension_loader.discover_and_load(
        router=router,
        dashboard_app=dashboard_instance.app,
        db_manager=db_manager,
        sync_db_pool=sync_db_pool,
        worker=worker,
        filter_instance=polling_filter,
        event_bus=event_bus,
        storage=storage,
    )

    runner = await start_dashboard(dashboard_instance, port=dashboard_port)
    logger.info("✅ Server v2 started. Mitmproxy and Dashboard are running on a SINGLE EVENT LOOP.")

    try:
        await master.run()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down... flushing event bus and closing connections.")
        await extension_loader.shutdown_all()
        storage.close() # Close V1 storage
        await worker.stop()
        await event_bus.stop()
        await db_manager.disconnect()
        if runner:
            await runner.cleanup()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Exited.")
