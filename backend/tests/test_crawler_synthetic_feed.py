import pytest
import json
from unittest.mock import patch, MagicMock

from proxify.platforms.facebook.auth import (
    TENANT_COOKIES,
    IN_MEMORY_COOKIES,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
    get_saved_tokens,
    extract_templates,
)
from proxify.platforms.facebook.crawler import FacebookCrawler


def setup_function():
    TENANT_TEMPLATES.clear()
    TENANT_COOKIES.clear()


def test_tenant_dict_proxy_len_bool_iter():
    """Verify that _TenantDictProxy correctly implements len, bool, and iteration."""
    assert not bool(IN_MEMORY_TEMPLATES)
    assert len(IN_MEMORY_TEMPLATES) == 0
    assert list(IN_MEMORY_TEMPLATES) == []

    # Insert an item via proxy
    IN_MEMORY_TEMPLATES["feed"] = {"headers": {}, "form_data": {"doc_id": "123"}}

    assert bool(IN_MEMORY_TEMPLATES)
    assert len(IN_MEMORY_TEMPLATES) == 1
    assert "feed" in IN_MEMORY_TEMPLATES
    assert list(IN_MEMORY_TEMPLATES) == ["feed"]
    assert IN_MEMORY_TEMPLATES.get("feed")["form_data"]["doc_id"] == "123"

    # Also verify TENANT_TEMPLATES["default"] received it
    assert "feed" in TENANT_TEMPLATES["default"]


def test_get_saved_tokens_multitenant():
    """Verify get_saved_tokens retrieves templates according to client_id."""
    import asyncio

    async def _run():
        # Empty
        tokens = await get_saved_tokens("tenant_a")
        assert tokens is None

        # Save to tenant_a
        TENANT_TEMPLATES["tenant_a"] = {"feed": {"form_data": {"fb_api_req_friendly_name": "FeedQuery"}}}
        tokens_a = await get_saved_tokens("tenant_a")
        assert tokens_a is not None
        assert tokens_a["feed"]["form_data"]["fb_api_req_friendly_name"] == "FeedQuery"

        # Default fallback when asking for other client without specific tenant
        IN_MEMORY_TEMPLATES["feed"] = {"form_data": {"fb_api_req_friendly_name": "DefaultFeed"}}
        tokens_b = await get_saved_tokens("tenant_b")
        assert tokens_b is not None
        assert tokens_b["feed"]["form_data"]["fb_api_req_friendly_name"] == "DefaultFeed"

    asyncio.run(_run())


def test_synthesize_feed_template():
    """Verify that FacebookCrawler._synthesize_feed_template creates a valid feed template."""
    TENANT_COOKIES["test_client"] = {
        "fb_dtsg": "NAcMockDtsg",
        "lsd": "mock_lsd",
        "user_id": "1000123456",
        "cookie": "c_user=1000123456; xs=mock_xs;",
        "user_agent": "Mozilla/5.0 TestAgent",
    }

    crawler = FacebookCrawler(client_id="test_client")
    tpl = crawler._synthesize_feed_template(
        group_id="apikhongngonxoagroup",
        raw_cookie="c_user=1000123456; xs=mock_xs;",
        client_id="test_client",
    )

    assert tpl is not None
    assert "headers" in tpl
    assert "form_data" in tpl
    assert tpl["form_data"]["fb_api_req_friendly_name"] == "GroupsCometFeedRegularStoriesPaginationQuery"
    assert tpl["form_data"]["fb_dtsg"] == "NAcMockDtsg"
    assert tpl["form_data"]["lsd"] == "mock_lsd"
    assert tpl["form_data"]["__user"] == "1000123456"

    # Check variables
    variables = json.loads(tpl["form_data"]["variables"])
    assert variables["id"] == "apikhongngonxoagroup"
    assert variables["sortingSetting"] == "CHRONOLOGICAL"
    assert variables["feedLocation"] == "GROUP"
    assert variables["renderLocation"] == "group"
    assert variables["privacySelectorRenderLocation"] == "COMET_STREAM"
    assert "__relay_internal__pv__GHLShouldChangeAdIdFieldNamerelayprovider" in variables

    # Verify cached in memory
    assert "feed" in TENANT_TEMPLATES["test_client"]
    assert "feed" in IN_MEMORY_TEMPLATES


def test_set_variables_populates_missing_baseline_keys():
    """Verify FacebookCrawler._set_variables augments sparse variables with all required Facebook parameters."""
    data = {"variables": json.dumps({"id": "some_group"})}
    cursor = FacebookCrawler._set_variables(data, "some_group", "cursor123")
    assert cursor == "cursor123"

    parsed_vars = json.loads(data["variables"])
    assert parsed_vars["id"] == "some_group"
    assert parsed_vars["sortingSetting"] == "CHRONOLOGICAL"
    assert parsed_vars["cursor"] == "cursor123"
    assert parsed_vars["feedLocation"] == "GROUP"
    assert parsed_vars["renderLocation"] == "group"


def test_crawler_resolve_cookie_tenant():
    """Verify _resolve_cookie correctly pulls from TENANT_COOKIES."""
    import asyncio

    async def _run():
        TENANT_COOKIES["client_x"] = {
            "cookie": "c_user=999999; xs=client_x_xs;",
        }

        crawler = FacebookCrawler(client_id="client_x")
        resolved = await crawler._resolve_cookie(
            client_cookie=None,
            tokens=None,
            client_id="client_x",
        )
        assert resolved == "c_user=999999; xs=client_x_xs;"

    asyncio.run(_run())

