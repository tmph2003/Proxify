import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from aiohttp import web
from proxify.sdk.base import BaseExtension
from proxify.sdk.context import ExtensionContext
from proxify.sdk.loader import ExtensionLoader


class SampleExtension(BaseExtension):
    id = "sample"
    name = "Sample Extension"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self, context: ExtensionContext) -> None:
        await super().initialize(context)
        self.initialized = True
        context.register_ui_page(title="Sample Page", path="/sample", order=10)

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.anyio
async def test_extension_lifecycle():
    ext = SampleExtension()
    assert ext.id == "sample"
    assert ext.name == "Sample Extension"

    mock_router = MagicMock()
    mock_app = web.Application()
    mock_db = MagicMock()
    mock_sync_pool = MagicMock()
    mock_worker = MagicMock()

    ctx = ExtensionContext(
        extension_id=ext.id,
        router=mock_router,
        dashboard_app=mock_app,
        db_manager=mock_db,
        sync_db_pool=mock_sync_pool,
        worker=mock_worker,
    )

    await ext.initialize(ctx)
    assert ext.initialized is True
    assert len(ctx._ui_pages) == 1
    assert ctx._ui_pages[0]["title"] == "Sample Page"

    await ext.shutdown()
    assert ext.shutdown_called is True


@pytest.mark.anyio
async def test_extension_context_capabilities():
    mock_router = MagicMock()
    mock_app = web.Application()
    mock_db = MagicMock()
    mock_sync_pool = MagicMock()
    mock_worker = MagicMock()
    mock_filter = MagicMock()

    ctx = ExtensionContext(
        extension_id="test_ext",
        router=mock_router,
        dashboard_app=mock_app,
        db_manager=mock_db,
        sync_db_pool=mock_sync_pool,
        worker=mock_worker,
        filter_instance=mock_filter,
    )

    # 1. Routes
    async def sample_handler(req):
        return web.Response(text="ok")

    ctx.register_route("GET", "/api/test_route", sample_handler)
    ctx.register_routes([web.get("/api/test_batch", sample_handler)])
    assert len(ctx._registered_routes) == 2

    # 2. Interceptors
    mock_observer = MagicMock()
    ctx.register_observer(mock_observer, domains=["example.com"])
    mock_router.register_observer.assert_called_once_with(mock_observer)

    mock_mutator = MagicMock()
    ctx.register_mutator(mock_mutator, domains=["test.org"])
    mock_router.register_mutator.assert_called_once_with(mock_mutator)

    # 3. Stream & Ignored Domains
    ctx.register_stream_domains(["stream.cdn.com"])
    mock_router.register_stream_domains.assert_called_once_with(["stream.cdn.com"])

    ctx.register_ignored_hosts(["passthrough.com"])
    mock_router.add_ignored_host.assert_called_once_with("passthrough.com")

    # 4. Polling Path
    ctx.register_polling_path("/api/frequent_poll")
    mock_filter.add_ignored_path.assert_called_once_with("/api/frequent_poll")


@pytest.mark.anyio
async def test_extension_loader_disabled():
    loader = ExtensionLoader(disabled=True)
    assert loader.is_enabled() is False

    mock_app = web.Application()
    loaded = await loader.discover_and_load(
        router=MagicMock(),
        dashboard_app=mock_app,
        db_manager=MagicMock(),
        sync_db_pool=MagicMock(),
        worker=MagicMock(),
    )
    assert len(loaded) == 0


@pytest.mark.anyio
async def test_extension_loader_nonexistent_dir(tmp_path):
    non_existent = tmp_path / "does_not_exist"
    loader = ExtensionLoader(extensions_dir=str(non_existent), disabled=False)

    mock_app = web.Application()
    loaded = await loader.discover_and_load(
        router=MagicMock(),
        dashboard_app=mock_app,
        db_manager=MagicMock(),
        sync_db_pool=MagicMock(),
        worker=MagicMock(),
    )
    assert len(loaded) == 0
