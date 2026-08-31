import asyncio
import logging
import os
from pathlib import Path
from aiohttp import web
from mitmproxy.tools.dump import DumpMaster
from mitmproxy.options import Options

from proxify.core.database import DatabaseManager
from proxify.core.eventbus import AsyncEventBus
from proxify.core.router import ProxyRouter
from proxify.core.worker import BackgroundWorker
from proxify.platforms.facebook.platform import FacebookPlatform
from proxify.plugins.zalo import ZaloPlugin

logger = logging.getLogger("proxify.server")

class ProxyAddon:
    """The central Mitmproxy Addon that delegates to the fast Router."""
    def __init__(self, router: ProxyRouter):
        self.router = router

    async def request(self, flow):
        await self.router.route_request(flow)

    async def responseheaders(self, flow):
        await self.router.route_responseheaders(flow)

    async def response(self, flow):
        await self.router.route_response(flow)

class V1GlobalObserver:
    """Wraps V1 interceptors to bridge mitmproxy flows to the legacy Global Dashboard."""
    target_domains = [] # Listen to all domains
    
    def __init__(self, broadcast_fn, storage):
        from proxify.core.listeners import DashboardBroadcaster, DatabaseWriter
        self.broadcaster = DashboardBroadcaster(broadcast_fn)
        self.db_writer = DatabaseWriter(storage)
        
    async def handle_request(self, flow):
        pass
        
    async def handle_response(self, flow):
        # Determine whether DB save is allowed based on V1 storage settings
        db_save = getattr(self.db_writer.storage, 'db_integration_enabled', False)
        if db_save:
            allowed_domains = getattr(self.db_writer.storage, 'db_allowed_domains', [])
            if allowed_domains:
                domain = flow.request.pretty_host or ""
                if not any(d in domain for d in allowed_domains):
                    db_save = False

        self.broadcaster(flow, db_save=db_save)
        self.db_writer(flow, db_save=db_save)

async def start_dashboard(storage, api_routes, port=8888):
    from proxify.dashboard import Dashboard
    # Instantiate the legacy dashboard
    dashboard = Dashboard(storage, port=port)
    
    # Add V2 API routes to the Dashboard's app
    dashboard.app.add_routes(api_routes)
    
    runner = web.AppRunner(dashboard.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Dashboard running on port {port}")
    return runner, dashboard

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

    # 3. Initialize Router & Platforms
    router = ProxyRouter()
    
    # In a real app, this would use a registry to auto-discover platforms
    fb_platform = FacebookPlatform(event_bus)
    
    for observer in fb_platform.get_observers():
        router.register_observer(observer)
        
    for mutator in fb_platform.get_mutators():
        router.register_mutator(mutator)

    # 4. Start Mitmproxy in the same event loop
    proxy_port = int(os.environ.get("PROXY_PORT", 8080))
    opts = Options(listen_host="0.0.0.0", listen_port=proxy_port, ssl_insecure=True, http2=False)
    master = DumpMaster(opts, with_termlog=True, with_dumper=False)
    master.addons.add(ProxyAddon(router))
    
    # Enable stealth mode for Facebook domains
    try:
        from proxify.stealth_addon import StealthUpstreamAddon
        stealth = StealthUpstreamAddon(target_domains=["facebook.com"])
        master.addons.add(stealth)
        logger.info("🛡️  Stealth Mode ENABLED in v2")
    except ImportError:
        logger.warning("Stealth module not found, skipping stealth mode.")

    # Load YouTube Plugin for ad-blocking
    try:
        from proxify.plugins.youtube import YouTubePlugin
        yt_plugin = YouTubePlugin(event_bus)
        for domain in yt_plugin.target_domains:
            router._insert(domain, yt_plugin, True)
        logger.info("📺 YouTube Plugin ENABLED in v2")
    except Exception as e:
        logger.error(f"Failed to load YouTube plugin: {e}")

    # 4.5. Initialize V1 RequestStorage and Global Observer
    from proxify.storage import RequestStorage
    storage = RequestStorage()
    
    # The V1 observer needs the `broadcast` function from the Dashboard.
    # Since we create Dashboard *after* this, we use a deferred callback.
    dashboard_instance = None
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
            
    global_observer = V1GlobalObserver(_deferred_broadcast, storage)
    router.register_observer(global_observer)
    
    # 5. Start aiohttp dashboard
    dashboard_port = int(os.environ.get("DASHBOARD_PORT", 8888))
    
    # Collect API routes
    all_routes = list(fb_platform.get_api_routes())
    
    # Initialize Facebook DB tables asynchronously
    try:
        from proxify.platforms.facebook.database import fb_db
        await asyncio.to_thread(fb_db.init_db)
        logger.info("[DB] Facebook DB initialized in background thread.")
    except Exception as e:
        logger.warning(f"Could not init Facebook DB: {e}")

    # Try to load Zalo routes
    try:
        zalo_plugin = ZaloPlugin(storage=None)
        all_routes.extend(zalo_plugin.get_api_routes())
        router.register_mutator(zalo_plugin)
        from proxify.platforms.zalo.database import zalo_db
        await asyncio.to_thread(zalo_db.init_db)
        logger.info("[DB] Zalo DB initialized in background thread.")
    except Exception as e:
        logger.warning(f"Could not load Zalo routes: {e}")

    runner, dashboard_instance = await start_dashboard(storage, all_routes, port=dashboard_port)
    
    logger.info("✅ Server v2 started. Mitmproxy and Dashboard are running on a SINGLE EVENT LOOP.")

    try:
        await master.run()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down... flushing event bus and closing connections.")
        storage.close() # Close V1 storage
        await worker.stop()
        await event_bus.stop()
        await db_manager.disconnect()
        await runner.cleanup()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Exited.")
