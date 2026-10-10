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
            await self.router.route_responseheaders(flow)
        except Exception as e:
            logger.error(f"Error in ProxyAddon.responseheaders: {e}", exc_info=True)

    async def response(self, flow):
        try:
            await self.router.route_response(flow)
        except Exception as e:
            logger.error(f"Error in ProxyAddon.response: {e}", exc_info=True)

class V1GlobalObserver:
    """Wraps V1 interceptors to bridge mitmproxy flows to the legacy Global Dashboard."""
    target_domains = [] # Listen to all domains
    
    def __init__(self, broadcast_fn, storage, ignored_hosts: list[str] = None):
        from proxify.core.listeners import DashboardBroadcaster, DatabaseWriter
        self.broadcaster = DashboardBroadcaster(broadcast_fn)
        self.db_writer = DatabaseWriter(storage)
        self.ignored_hosts = [h.strip().lower() for h in (ignored_hosts or []) if h.strip()]
        
    async def handle_request(self, flow):
        pass
        
    async def handle_response(self, flow):
        if not flow or not flow.request or not flow.response:
            return
        raw_host = flow.request.pretty_host or ""
        domain = raw_host.split(":", 1)[0].strip().lower()
        if any(domain == h or domain.endswith('.' + h) for h in self.ignored_hosts):
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

    # 2.5 Parse ignored hosts
    import re
    raw_ignore = os.getenv(
        "IGNORE_HOSTS",
        "captive.apple.com,bag.itunes.apple.com,p163-quota.icloud.com,mcs-sg.tiktokv.com,mon-sg.tiktokv.com,im-ws-sg.tiktok.com,zadn.vn,zing.vn,mcp.docker.com,api.docker.com,desktop.docker.com,mail.google.com,chat.google.com,accounts.google.com,clients6.google.com,client-channel.google.com,contacts.google.com,meet.google.com,drive.google.com,docs.google.com,github.com,githubassets.com,githubusercontent.com,microsoft.com,windowsupdate.com,live.com,office.com,msftncsi.com,googlevideo.com,google.com,gvt2.com,1e100.net,gstatic.com",
    )
    ignored_hosts = [h.strip().lstrip("*.").split(":", 1)[0].lower() for h in raw_ignore.split(",") if h.strip()]
    ignore_patterns = [rf"(?:^|\.){re.escape(h)}(?::|$)" for h in ignored_hosts]
    logger.info(f"🚫 Ignored Hosts (Passthrough): {ignored_hosts}")

    # 3. Initialize Router
    router = ProxyRouter(ignored_hosts=ignored_hosts)

    # 4. Start Mitmproxy in the same event loop
    proxy_port = int(os.environ.get("PROXY_PORT", 8080))
    opts = Options(
        listen_host="0.0.0.0",
        listen_port=proxy_port,
        ssl_insecure=True,
        http2=True,
        ignore_hosts=ignore_patterns,
    )
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
            
    global_observer = V1GlobalObserver(_deferred_broadcast, storage, ignored_hosts=ignored_hosts)
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
