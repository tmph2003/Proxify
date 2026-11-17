import asyncio
import socket
from urllib.parse import urlparse
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from mitmproxy.test import tflow
import mitmproxy.certs

from proxify.core.router import (
    ProxyRouter,
    _STREAM_EXTENSIONS,
    _STREAM_CONTENT_TYPES,
)
from proxify.core.listeners import DashboardBroadcaster, DatabaseWriter
from proxify.server import (
    windows_connection_reset_handler,
    V1GlobalObserver,
    _NoDelaySocket,
)


# =====================================================================
# 1. Radix Trie Routing Cache & Invalidation Tests
# =====================================================================

def test_router_cache_hits_misses_and_lookup_results():
    router = ProxyRouter()

    obs_global = MagicMock()
    obs_global.target_domains = []
    router.register_observer(obs_global)

    mut_example = MagicMock()
    mut_example.target_domains = ["example.com"]
    router.register_mutator(mut_example)

    mut_sub = MagicMock()
    mut_sub.target_domains = ["api.example.com"]
    router.register_mutator(mut_sub)

    # Miss 1: First lookup on sub domain
    obs, mut = router._search("api.example.com")
    assert router._cache_misses == 1
    assert router._cache_hits == 0
    assert obs_global in obs
    assert mut_example in mut
    assert mut_sub in mut
    assert "api.example.com" in router._search_cache

    # Hit 1: Repeat lookup on same domain
    obs2, mut2 = router._search("api.example.com")
    assert router._cache_misses == 1
    assert router._cache_hits == 1
    assert obs2 == obs
    assert mut2 == mut

    # Hit 2: Port-tagged domain maps to clean domain in cache
    obs3, mut3 = router._search("api.example.com:443")
    assert router._cache_misses == 1
    assert router._cache_hits == 2
    assert obs3 == obs
    assert mut3 == mut

    # Miss 2: Different domain
    obs4, mut4 = router._search("other.com")
    assert router._cache_misses == 2
    assert router._cache_hits == 2
    assert mut_example not in mut4
    assert mut_sub not in mut4
    assert obs_global in obs4


def test_router_cache_invalidation_on_dynamic_registration():
    router = ProxyRouter()

    mut_a = MagicMock()
    mut_a.target_domains = ["target.org"]
    router.register_mutator(mut_a)

    _, matched = router._search("target.org")
    assert mut_a in matched
    assert "target.org" in router._search_cache

    # Register dynamic observer -> must invalidate cache
    obs_new = MagicMock()
    obs_new.target_domains = ["target.org"]
    router.register_observer(obs_new)
    assert len(router._search_cache) == 0

    # Next search is a fresh miss and includes both
    new_obs, new_mut = router._search("target.org")
    assert obs_new in new_obs
    assert mut_a in new_mut
    assert "target.org" in router._search_cache

    # Register dynamic mutator -> must invalidate cache again
    mut_b = MagicMock()
    mut_b.target_domains = ["target.org"]
    router.register_mutator(mut_b)
    assert len(router._search_cache) == 0

    # Verify manual invalidate_cache()
    router._search("target.org")
    assert len(router._search_cache) == 1
    router.invalidate_cache()
    assert len(router._search_cache) == 0


def test_router_lru_cache_eviction_bounded():
    # Router with small cache maxsize = 3
    router = ProxyRouter(cache_maxsize=3)

    for i in range(1, 4):
        router._search(f"d{i}.com")
    assert len(router._search_cache) == 3
    assert list(router._search_cache.keys()) == ["d1.com", "d2.com", "d3.com"]

    # Access d1.com -> moves to end (most recently used)
    router._search("d1.com")
    assert list(router._search_cache.keys()) == ["d2.com", "d3.com", "d1.com"]

    # Access d4.com -> exceeds 3, evicts d2.com (oldest)
    router._search("d4.com")
    assert len(router._search_cache) == 3
    assert "d2.com" not in router._search_cache
    assert list(router._search_cache.keys()) == ["d3.com", "d1.com", "d4.com"]


# =====================================================================
# 2. Native URL Path Parsing Equivalence Tests
# =====================================================================

def test_native_url_path_parsing_equivalence():
    test_urls = [
        "https://example.com/api/v1/users",
        "https://example.com/api/v1/users?page=2&limit=50",
        "https://example.com/download/file.zip?token=abc#download-section",
        "https://example.com/",
        "http://example.com:8080/path/to/resource.png?v=1.2.3",
        "https://sub.domain.co.uk:443/complex/path/name.tar.gz?query=1&arg=2",
        "https://example.com/graphql?query={me{id}}",
    ]

    for url in test_urls:
        parsed = urlparse(url)
        expected_path = parsed.path.lower()

        # Simulate flow.request with native path
        # In mitmproxy, request.path contains the path + query string (as in HTTP request line)
        full_path = parsed.path + (("?" + parsed.query) if parsed.query else "") + (("#" + parsed.fragment) if parsed.fragment else "")
        native_path = full_path.split("?")[0].split("#")[0].lower()

        assert native_path == expected_path, f"Mismatch for URL {url}: native={native_path}, expected={expected_path}"


def test_dashboard_broadcaster_native_url_parsing():
    received = []
    broadcaster = DashboardBroadcaster(lambda s: received.append(s))

    flow = tflow.tflow(resp=True)
    flow.request.host = "api.service.io"
    flow.request.path = "/v2/items?filter=active#section"
    flow.request.method = "GET"
    flow.response.status_code = 200

    broadcaster(flow, db_save=False)
    assert len(received) == 1
    summary = received[0]
    assert summary["domain"] == "api.service.io"
    assert summary["path"] == "/v2/items"
    assert summary["status_code"] == 200


def test_database_writer_native_url_parsing():
    saved_data = []
    mock_storage = MagicMock()
    mock_storage.save_request_async = lambda d, callback=None: saved_data.append(d)

    writer = DatabaseWriter(mock_storage)

    # 1. HTTPS standard port (443) -> port should be None
    flow_https = tflow.tflow(resp=True)
    flow_https.request.scheme = "https"
    flow_https.request.host = "secure.example.com"
    flow_https.request.port = 443
    flow_https.request.path = "/api/login?ref=home"
    flow_https.response.status_code = 200

    writer(flow_https, db_save=True)
    assert len(saved_data) == 1
    d1 = saved_data[0]
    assert d1["scheme"] == "https"
    assert d1["domain"] == "secure.example.com"
    assert d1["port"] is None
    assert d1["path"] == "/api/login"
    assert d1["query_string"] == "ref=home"

    # 2. Custom port (8443) -> port should be preserved
    flow_custom = tflow.tflow(resp=True)
    flow_custom.request.scheme = "https"
    flow_custom.request.host = "internal.example.com"
    flow_custom.request.port = 8443
    flow_custom.request.path = "/status"
    flow_custom.response.status_code = 200

    writer(flow_custom, db_save=True)
    assert len(saved_data) == 2
    d2 = saved_data[1]
    assert d2["domain"] == "internal.example.com"
    assert d2["port"] == 8443
    assert d2["path"] == "/status"
    assert d2["query_string"] == ""


# =====================================================================
# 3. Streaming Binary Archives & OOM Protection Tests
# =====================================================================

def test_streaming_extensions_and_content_types_inventory():
    expected_extensions = [
        ".zip", ".7z", ".tar", ".gz", ".iso", ".bin", ".exe", ".msi",
        ".pdf", ".apk", ".dmg", ".pkg", ".bz2", ".xz",
    ]
    for ext in expected_extensions:
        assert ext in _STREAM_EXTENSIONS, f"Missing streaming extension: {ext}"

    expected_content_types = [
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/x-zip-compressed",
        "application/x-tar",
        "application/gzip",
    ]
    for ct in expected_content_types:
        assert ct in _STREAM_CONTENT_TYPES, f"Missing streaming content-type: {ct}"


@pytest.mark.anyio
async def test_router_streams_binary_archives_and_chunked_downloads():
    router = ProxyRouter()

    # 1. Chunked octet-stream download without content-length header
    f_chunked = MagicMock()
    f_chunked.request.path = "/releases/v1.0.0/firmware.bin"
    f_chunked.request.pretty_host = "downloads.example.org"
    f_chunked.response.headers = {"content-type": "application/octet-stream"}
    f_chunked.response.stream = False

    await router.route_responseheaders(f_chunked)
    assert f_chunked.response.stream is True

    # 2. PDF document streaming
    f_pdf = MagicMock()
    f_pdf.request.path = "/reports/annual_2026.pdf?signature=valid"
    f_pdf.request.pretty_host = "docs.example.org"
    f_pdf.response.headers = {"content-type": "application/pdf"}
    f_pdf.response.stream = False

    await router.route_responseheaders(f_pdf)
    assert f_pdf.response.stream is True

    # 3. Zip archive download with generic content-type but .zip extension
    f_zip = MagicMock()
    f_zip.request.path = "/files/dataset.zip?download=true"
    f_zip.request.pretty_host = "data.example.org"
    f_zip.response.headers = {"content-type": "application/unknown"}
    f_zip.response.stream = False

    await router.route_responseheaders(f_zip)
    assert f_zip.response.stream is True

    # 4. Standard HTML page should NOT be streamed
    f_html = MagicMock()
    f_html.request.path = "/index.html"
    f_html.request.pretty_host = "www.example.org"
    f_html.response.headers = {"content-type": "text/html; charset=utf-8", "content-length": "1024"}
    f_html.response.stream = False

    await router.route_responseheaders(f_html)
    assert f_html.response.stream is False


# =====================================================================
# 4. Mitmproxy TLS CertStore Capacity Expansion Tests
# =====================================================================

def test_mitmproxy_certstore_capacity_is_2048():
    assert mitmproxy.certs.CertStore.STORE_CAP == 2048


# =====================================================================
# 5. Windows Event Loop Exception Handler & Socket Tuning Tests
# =====================================================================

def test_windows_connection_reset_handler_suppression():
    mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)

    # 1. ConnectionResetError with WinError 10054 -> must be suppressed
    exc_10054 = ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
    exc_10054.winerror = 10054
    context_10054 = {"message": "Fatal read error on transport", "exception": exc_10054}

    windows_connection_reset_handler(mock_loop, context_10054)
    mock_loop.default_exception_handler.assert_not_called()

    # 2. ConnectionAbortedError -> must be suppressed
    exc_aborted = ConnectionAbortedError("Connection aborted")
    context_aborted = {"message": "Transport endpoint disconnected", "exception": exc_aborted}

    windows_connection_reset_handler(mock_loop, context_aborted)
    mock_loop.default_exception_handler.assert_not_called()

    # 3. Context message containing 10054 without explicit exception object -> must be suppressed
    context_msg = {"message": "Future exception was never retrieved: [WinError 10054]"}
    windows_connection_reset_handler(mock_loop, context_msg)
    mock_loop.default_exception_handler.assert_not_called()

    # 4. Critical unhandled exception (e.g. ValueError, RuntimeError) -> must NOT be suppressed
    exc_critical = RuntimeError("Database connection pool exhausted")
    context_critical = {"message": "Unhandled error in worker", "exception": exc_critical}

    windows_connection_reset_handler(mock_loop, context_critical)
    mock_loop.default_exception_handler.assert_called_once_with(context_critical)


def test_socket_tcp_nodelay_enabled_by_default():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        opt_val = s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        assert opt_val == 1, f"Expected TCP_NODELAY=1, got {opt_val}"
    finally:
        s.close()


@pytest.mark.anyio
async def test_v1_global_observer_bypasses_router_ignored_host():
    router = ProxyRouter(ignored_hosts=["ignored-cdn.com"])
    mock_broadcaster = MagicMock()
    mock_storage = MagicMock()

    observer = V1GlobalObserver(mock_broadcaster, mock_storage, ignored_hosts=["ignored-cdn.com"], router=router)

    # 1. Ignored host -> should return early and not broadcast
    flow_ignored = MagicMock()
    flow_ignored.metadata = {}
    flow_ignored.request.pretty_host = "static.ignored-cdn.com"
    flow_ignored.request.path = "/asset.png"
    flow_ignored.response.stream = False

    await observer.handle_response(flow_ignored)
    mock_broadcaster.assert_not_called()

    # 2. Non-ignored host -> should broadcast
    flow_valid = MagicMock()
    flow_valid.metadata = {}
    flow_valid.request.pretty_host = "app.active-service.com"
    flow_valid.request.path = "/api/data"
    flow_valid.request.pretty_url = "https://app.active-service.com/api/data"
    flow_valid.response.stream = False
    flow_valid.response.headers = {"content-type": "application/json"}
    flow_valid.response.raw_content = b'{"ok": true}'
    flow_valid.response.status_code = 200

    await observer.handle_response(flow_valid)
    assert mock_broadcaster.call_count >= 1
