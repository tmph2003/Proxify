import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from proxify.platforms.facebook.crawler import FacebookCrawler
from proxify.platforms.facebook.bridge import ExtensionBridge


def test_parse_metrics_from_graphql_success():
    """Verify parsing reaction count, comment count, and feedback ID from valid GraphQL response."""
    sample_response = json.dumps({
        "data": {
            "node": {
                "__typename": "Feedback",
                "id": "ZmVlZGJhY2s6OTg3NjU0MzIx",
                "reaction_count": {"count": 142},
                "comment_rendering_instance_for_feed_location": {
                    "comments": {
                        "total_count": 38
                    }
                }
            }
        }
    })
    
    reactions, comments, feedback_id, is_active = FacebookCrawler._parse_metrics_from_graphql(sample_response)
    assert reactions == 142
    assert comments == 38
    assert feedback_id == "ZmVlZGJhY2s6OTg3NjU0MzIx"
    assert is_active is True


def test_parse_metrics_from_graphql_deleted_post():
    """Verify deleted or unavailable post is correctly flagged as is_active = False."""
    error_response = json.dumps({
        "errors": [
            {
                "message": "This content isn't available right now",
                "severity": "CRITICAL"
            }
        ]
    })
    
    reactions, comments, feedback_id, is_active = FacebookCrawler._parse_metrics_from_graphql(error_response)
    assert is_active is False
    assert reactions is None
    assert comments is None


def test_parse_metrics_from_graphql_null_node():
    """Verify null node in GraphQL indicates inactive / deleted post."""
    null_node_response = json.dumps({
        "data": {
            "node": None
        }
    })
    
    reactions, comments, feedback_id, is_active = FacebookCrawler._parse_metrics_from_graphql(null_node_response)
    assert is_active is False


def test_synthesize_comment_template():
    """Verify synthetic CommentsListComponentsPaginationQuery template structure."""
    crawler = FacebookCrawler()
    feed_tpl = {
        "headers": {"User-Agent": "TestUA", "X-Custom": "val"},
        "form_data": {"fb_dtsg": "live_token_123", "jazoest": "25432"}
    }
    
    tpl = crawler._synthesize_comment_template("123456789", feed_tpl)
    assert tpl["form_data"]["fb_api_req_friendly_name"] == "CommentsListComponentsPaginationQuery"
    assert tpl["form_data"]["doc_id"] == "27973447728944010"
    assert tpl["form_data"]["fb_dtsg"] == "live_token_123"
    
    variables = json.loads(tpl["form_data"]["variables"])
    # 123456789 should be base64-encoded as feedback:123456789
    assert variables["id"] == "ZmVlZGJhY2s6MTIzNDU2Nzg5"
    assert variables["commentsIntentToken"] == "CHRONOLOGICAL_UNFILTERED_INTENT_V1"
    assert tpl["headers"]["X-FB-Friendly-Name"] == "CommentsListComponentsPaginationQuery"


def test_bridge_execute_request_blocks_html_permalinks():
    """Verify ExtensionBridge immediately blocks non-GraphQL requests to prevent checkpoints."""
    async def _run():
        bridge = ExtensionBridge()
        unsafe_url = "https://www.facebook.com/groups/techviet/posts/999888777"
        
        res = await bridge.execute_request(unsafe_url, method="GET", client_id="test_client")
        assert res["status"] == "error"
        assert res["status_code"] == 403
        assert "Only /api/graphql/" in res["error"]
        
        # Confirm nothing was added to queue
        assert bridge.get_job(client_id="test_client") is None

    import asyncio
    asyncio.run(_run())


def test_resolve_numeric_group_id_digits_only():
    """Verify numeric ID returns immediately without DB or network calls."""
    async def _run():
        from proxify.platforms.facebook.crawler import _resolve_numeric_group_id
        res = await _resolve_numeric_group_id("1234567890", "", None)
        assert res == "1234567890"

    import asyncio
    asyncio.run(_run())


def test_extract_metrics_from_html_success():
    """Verify extracting reaction and comment metrics from embedded JSON in Facebook HTML."""
    sample_html = """
    <!DOCTYPE html><html><body>
    <script type="application/json">
    {
        "require": [],
        "define": [],
        "instances": [],
        "elements": [],
        "entry_point": {
            "__typename": "Story",
            "feedback": {
                "id": "ZmVlZGJhY2s6Mjg0MDU2OTc0Mjk5NjU3Ng=="
            },
            "comet_ufi_summary_and_actions_renderer": {
                "feedback": {
                    "reaction_count": {"count": 42}
                }
            },
            "comment_rendering_instance": {
                "comments": {
                    "total_count": 15
                }
            }
        }
    }
    </script>
    </body></html>
    """
    rc, cc, fbid, is_active, status = FacebookCrawler.extract_metrics_from_html(sample_html)
    assert rc == 42
    assert cc == 15
    assert fbid == "ZmVlZGJhY2s6Mjg0MDU2OTc0Mjk5NjU3Ng=="
    assert is_active is True
    assert status == "ok"


def test_extract_metrics_from_html_unavailable():
    """Verify deleted or unavailable post HTML is correctly flagged."""
    deleted_html = "<html><body>Bạn hiện không xem được nội dung này</body></html>"
    rc, cc, fbid, is_active, status = FacebookCrawler.extract_metrics_from_html(deleted_html)
    assert is_active is False
    assert status == "unavailable"

