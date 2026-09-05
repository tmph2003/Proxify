import json
from pathlib import Path
import pytest
from proxify.platforms.facebook.bridge import bridge
from proxify.platforms.facebook.crawler import FacebookCrawler


def test_manifest_storage_permission():
    """Verify chrome extension manifest contains 'storage' permission."""
    manifest_path = Path(__file__).resolve().parent.parent / "chrome_extension" / "manifest.json"
    assert manifest_path.exists(), "manifest.json should exist"
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "storage" in data.get("permissions", []), "manifest.json must have 'storage' in permissions"


def test_crawler_client_id_bridge_isolation():
    """Verify crawler correctly tracks and queries bridge connection with isolated client_id."""
    crawler_tenant_x = FacebookCrawler(client_id="tenant_x")
    crawler_tenant_y = FacebookCrawler(client_id="tenant_y")

    # Initially neither is connected
    assert not bridge.is_connected(client_id="tenant_x")
    assert not bridge.is_connected(client_id="tenant_y")

    # Simulate tenant_x polling
    bridge.get_job(client_id="tenant_x")
    assert bridge.is_connected(client_id="tenant_x")
    assert not bridge.is_connected(client_id="tenant_y")

    assert crawler_tenant_x.client_id == "tenant_x"
    assert crawler_tenant_y.client_id == "tenant_y"


def test_crawler_safe_request_comment_does_not_set_feed_stop_flag():
    """Verify that comment crawl failures do not set _stop_flag on feed crawler."""
    import asyncio

    async def _test():
        crawler = FacebookCrawler(client_id="test_stop_flag_client")
        crawler._stop_flag = False

        # Simulate a failed comment request when bridge is offline
        resp = await crawler._safe_request("GET", "https://facebook.com/fake", is_comment_crawl=True)
        assert resp.is_blocked is True
        # Crucial: is_comment_crawl must NOT set self._stop_flag = True
        assert crawler._stop_flag is False

    asyncio.run(_test())
