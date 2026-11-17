import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from mitmproxy import http
from proxify.core.router import ProxyRouter
from proxify.core.database import DatabaseManager
from proxify.dashboard import Dashboard


def test_proxy_router_is_ignored_strict_boundary():
    router = ProxyRouter(ignored_hosts=[
        "github.com",
        "mail.google.com",
        "clients6.google.com",
        "zadn.vn",
        "zing.vn",
        "microsoft.com",
    ])

    # Exact matches
    assert router.is_ignored("github.com") is True
    assert router.is_ignored("mail.google.com") is True
    assert router.is_ignored("zadn.vn") is True
    assert router.is_ignored("zing.vn") is True
    assert router.is_ignored("microsoft.com") is True

    # Valid subdomains
    assert router.is_ignored("api.github.com") is True
    assert router.is_ignored("raw.github.com") is True
    assert router.is_ignored("sub.mail.google.com") is True
    assert router.is_ignored("0.clients6.google.com") is True
    assert router.is_ignored("img.zadn.vn") is True
    assert router.is_ignored("news.zing.vn") is True

    # Lookalikes, substrings, and foreign domains MUST NOT be ignored
    assert router.is_ignored("fake-github.com") is False
    assert router.is_ignored("mygithub.com") is False
    assert router.is_ignored("github.com.attacker.com") is False
    assert router.is_ignored("amazing.vn") is False
    assert router.is_ignored("notzadn.vn") is False
    assert router.is_ignored("evilmicrosoft.com") is False
    assert router.is_ignored("youtube.com") is False
    assert router.is_ignored("chat.zalo.me") is False
    assert router.is_ignored("") is False


@pytest.mark.anyio
async def test_proxy_router_route_responseheaders_malformed_content_length():
    router = ProxyRouter(ignored_hosts=["github.com"])

    # Mock flow with malformed content-length header
    mock_flow = MagicMock()
    mock_flow.request.pretty_url = "https://example.com/data"
    mock_flow.request.pretty_host = "example.com"
    mock_flow.response.headers = {
        "content-type": "text/html",
        "content-length": "malformed_number, 5000",
    }
    mock_flow.response.stream = False

    # Should not raise ValueError
    await router.route_responseheaders(mock_flow)
    assert mock_flow.response.stream is False


@pytest.mark.anyio
async def test_proxy_router_stream_domains_strict():
    router = ProxyRouter()

    # Valid googlevideo stream
    flow_valid = MagicMock()
    flow_valid.request.pretty_url = "https://r1---sn-abc.googlevideo.com/videoplayback"
    flow_valid.request.pretty_host = "r1---sn-abc.googlevideo.com"
    flow_valid.response.headers = {"content-type": "application/octet-stream"}
    flow_valid.response.stream = False

    await router.route_responseheaders(flow_valid)
    assert flow_valid.response.stream is True

    # Lookalike domain should not trigger streaming unconditionally
    flow_lookalike = MagicMock()
    flow_lookalike.request.pretty_url = "https://evilgooglevideo.com/api"
    flow_lookalike.request.pretty_host = "evilgooglevideo.com"
    flow_lookalike.response.headers = {"content-type": "text/html"}
    flow_lookalike.response.stream = False

    await router.route_responseheaders(flow_lookalike)
    assert flow_lookalike.response.stream is False


@pytest.mark.anyio
async def test_database_manager_connect_retry_resilience():
    db = DatabaseManager()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_connect = AsyncMock(side_effect=[Exception("DB locked"), mock_conn])
    with patch("aiosqlite.connect", new=mock_connect):
        with patch.object(db, "_init_core_schema", new_callable=AsyncMock) as mock_schema:
            await db.connect("test.db", max_retries=2, retry_interval=0.01)
            assert db.pool == mock_conn
            assert mock_connect.call_count == 2
            mock_schema.assert_awaited_once()

    # Verify that exhausting retries raises exception
    failing_connect = AsyncMock(side_effect=Exception("Persistent connection failure"))
    with patch("aiosqlite.connect", new=failing_connect):
        with pytest.raises(Exception, match="Persistent connection failure"):
            await db.connect("fail.db", max_retries=2, retry_interval=0.01)


@pytest.mark.anyio
async def test_dashboard_routes_registration_and_endpoints():
    mock_storage = MagicMock()
    mock_storage.db_integration_enabled = True
    mock_storage.db_allowed_domains = ["example.com"]
    mock_storage.retention_days = 7

    server = Dashboard(storage=mock_storage, port=8888)

    # Verify routes registered
    routes = [r.resource.canonical for r in server.app.router.routes()]
    assert "/api/config" in routes
    assert "/api/health" in routes
    assert "/api/status" in routes

    # 1. /api/health
    req_health = make_mocked_request("GET", "/api/health")
    resp_health = await server._handle_health(req_health)
    assert resp_health.status == 200
    import json
    data_health = json.loads(resp_health.text)
    assert data_health["status"] == "healthy"
    assert data_health["port"] == 8888

    # 2. /api/config
    req_config = make_mocked_request("GET", "/api/config")
    resp_config = await server._handle_get_config(req_config)
    assert resp_config.status == 200
    data_config = json.loads(resp_config.text)
    assert data_config["retention_days"] == 7
    assert data_config["db_integration_enabled"] is True


@pytest.mark.anyio
async def test_proxy_router_handles_none_and_empty_host_gracefully():
    router = ProxyRouter(ignored_hosts=["github.com"])
    
    # 1. is_ignored with None or empty
    assert router.is_ignored(None) is False
    assert router.is_ignored("") is False

    # 2. _search with None or empty must return globals, no AttributeError
    obs, mut = router._search(None)
    assert isinstance(obs, list)
    assert isinstance(mut, list)
    obs_empty, mut_empty = router._search("")
    assert isinstance(obs_empty, list)

    # 3. route_request with None pretty_host
    flow_none = MagicMock()
    flow_none.request.pretty_host = None
    flow_none.request.pretty_url = None
    await router.route_request(flow_none)

    # 4. route_response with None pretty_host
    flow_none.response.headers = {}
    await router.route_response(flow_none)

    # 5. route_responseheaders with None pretty_host
    await router.route_responseheaders(flow_none)


@pytest.mark.anyio
async def test_proxy_router_port_tagged_host_matches_search_and_stream_and_ignored():
    router = ProxyRouter(ignored_hosts=["github.com", "mail.google.com"])
    
    # 1. is_ignored with port
    assert router.is_ignored("github.com:443") is True
    assert router.is_ignored("mail.google.com:443") is True
    assert router.is_ignored("sub.mail.google.com:443") is True
    assert router.is_ignored("evilgithub.com:443") is False

    # 2. _search with port matches registered mutator
    mock_mut = MagicMock()
    mock_mut.target_domains = ["youtube.com"]
    router.register_mutator(mock_mut)
    _, matched = router._search("youtube.com:443")
    assert mock_mut in matched
    _, matched_sub = router._search("www.youtube.com:443")
    assert mock_mut in matched_sub

    # 3. googlevideo.com:443 stream matching
    flow_stream = MagicMock()
    flow_stream.request.pretty_url = "https://r1---sn-abc.googlevideo.com:443/videoplayback"
    flow_stream.request.pretty_host = "r1---sn-abc.googlevideo.com:443"
    flow_stream.response.headers = {"content-type": "application/octet-stream"}
    flow_stream.response.stream = False
    await router.route_responseheaders(flow_stream)
    assert flow_stream.response.stream is True


@pytest.mark.anyio
async def test_dashboard_toggle_db_invalid_json_handled():
    mock_storage = MagicMock()
    server = Dashboard(storage=mock_storage, port=8888)

    req_invalid = make_mocked_request("POST", "/api/toggle_db", payload=b"not a valid json")
    resp = await server._handle_toggle_db(req_invalid)
    assert resp.status == 400


def test_database_pool_recreates_closed_pool():
    import sqlite3
    from proxify.database.connection import DatabasePool
    dbp = DatabasePool(db_path=":memory:")

    # 1. Acquire initial SQLite connection
    conn1 = dbp.get_connection()
    assert conn1 is not None
    assert isinstance(conn1, sqlite3.Connection)
    assert dbp._conn is conn1

    # 2. Close connection pool
    dbp.close()
    assert dbp._conn is None

    # 3. Requesting connection again recreates new SQLite connection
    conn2 = dbp.get_connection()
    assert conn2 is not None
    assert isinstance(conn2, sqlite3.Connection)
    assert conn2 != conn1
    assert dbp._conn is conn2

    # 4. Context manager connection() works after close
    dbp.close()
    assert dbp._conn is None
    with dbp.connection() as conn3:
        assert conn3 is not None
        assert isinstance(conn3, sqlite3.Connection)
        assert conn3 != conn2

    dbp.close()


def test_router_search_deduplicates_interceptors_across_parent_and_child_domains():
    router = ProxyRouter()
    mock_mutator = MagicMock()
    mock_mutator.target_domains = ["example.com", "sub.example.com"]
    router.register_mutator(mock_mutator)

    obs, muts = router._search("sub.example.com")
    assert muts.count(mock_mutator) == 1
    assert len(muts) == 1


@pytest.mark.anyio
async def test_extension_context_accumulates_target_domains():
    from proxify.sdk.context import ExtensionContext
    router = ProxyRouter()
    ctx = ExtensionContext(
        "test_ext",
        router=router,
        dashboard_app=MagicMock(),
        db_manager=MagicMock(),
        sync_db_pool=MagicMock(),
        worker=MagicMock(),
        filter_instance=MagicMock(),
        event_bus=MagicMock(),
        storage=MagicMock(),
    )
    mock_mut = MagicMock()
    mock_mut.target_domains = ["domain1.com"]
    ctx.register_mutator(mock_mut, domains=["domain2.com"])
    ctx.register_mutator(mock_mut, domains=["domain3.com"])

    assert "domain1.com" in mock_mut.target_domains
    assert "domain2.com" in mock_mut.target_domains
    assert "domain3.com" in mock_mut.target_domains


@pytest.mark.anyio
async def test_proxy_router_record_filters():
    router = ProxyRouter()
    router.register_record_filter(lambda d, p, u: d == "telemetry.example.com" or "/heartbeat" in p)

    assert router.should_skip_record("telemetry.example.com", "/v1/ping", "https://telemetry.example.com/v1/ping") is True
    assert router.should_skip_record("api.example.com", "/v1/heartbeat", "https://api.example.com/v1/heartbeat") is True
    assert router.should_skip_record("api.example.com", "/v1/orders", "https://api.example.com/v1/orders") is False


@pytest.mark.anyio
async def test_proxy_addon_catches_unhandled_exceptions_gracefully():
    from proxify.server import ProxyAddon

    failing_router = MagicMock()
    failing_router.route_request = AsyncMock(side_effect=RuntimeError("Simulated router crash"))
    failing_router.route_responseheaders = AsyncMock(side_effect=RuntimeError("Simulated router crash"))
    failing_router.route_response = AsyncMock(side_effect=RuntimeError("Simulated router crash"))

    addon = ProxyAddon(failing_router)
    dummy_flow = MagicMock()

    # None of these should raise
    await addon.request(dummy_flow)
    await addon.responseheaders(dummy_flow)
    await addon.response(dummy_flow)


@pytest.mark.anyio
async def test_proxy_router_smart_js_and_css_streaming():
    """Verify .css is always streamed and .js is streamed unless a mutator with mutates_js=True matches."""
    router = ProxyRouter()

    non_js_mutator = MagicMock()
    non_js_mutator.target_domains = ["video.example.com"]
    non_js_mutator.mutates_js = False
    router.register_mutator(non_js_mutator)

    js_mutator = MagicMock()
    js_mutator.target_domains = ["app.example.com"]
    js_mutator.mutates_js = True
    router.register_mutator(js_mutator)

    def make_flow(url: str, host: str, content_type: str = "application/javascript"):
        f = MagicMock()
        f.request.pretty_url = url
        f.request.pretty_host = host
        f.response.headers = {"content-type": content_type}
        f.response.stream = False
        return f

    # 1. General web JS bundles MUST stream directly (0 RAM buffering)
    f_gh = make_flow("https://github.githubassets.com/assets/app.js", "github.githubassets.com")
    await router.route_responseheaders(f_gh)
    assert f_gh.response.stream is True

    # 2. Mutator with mutates_js=False MUST still stream .js directly
    f_vid = make_flow("https://video.example.com/player/base.js", "video.example.com")
    await router.route_responseheaders(f_vid)
    assert f_vid.response.stream is True

    # 3. CSS stylesheets MUST stream unconditionally even on js_mutator domains
    f_css = make_flow("https://app.example.com/styles/main.css", "app.example.com", "text/css")
    await router.route_responseheaders(f_css)
    assert f_css.response.stream is True

    # 4. Mutator with mutates_js=True MUST NOT stream .js (so mutator can inspect/modify body)
    f_app = make_flow("https://app.example.com/js/app.js", "app.example.com")
    await router.route_responseheaders(f_app)
    assert f_app.response.stream is False

