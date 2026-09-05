import asyncio
import pytest
from proxify.platforms.facebook.bridge import ExtensionBridge


def test_multitenant_bridge_queue_isolation():
    """Verify that jobs queued for Client A cannot be retrieved by Client B."""
    async def _run():
        bridge = ExtensionBridge()

        # Dispatch job for Client A in background (must be /api/graphql per security invariant)
        task_a = asyncio.create_task(
            bridge.execute_request("https://www.facebook.com/api/graphql/test_a", client_id="client_A", timeout=5)
        )
        # Dispatch job for Client B in background
        task_b = asyncio.create_task(
            bridge.execute_request("https://www.facebook.com/api/graphql/test_b", client_id="client_B", timeout=5)
        )

        await asyncio.sleep(0.05)

        # Client A should see only job for Client A
        job_a = bridge.get_job(client_id="client_A")
        assert job_a is not None
        assert job_a["url"] == "https://www.facebook.com/api/graphql/test_a"
        assert job_a["client_id"] == "client_A"

        # Client A queue is now empty
        assert bridge.get_job(client_id="client_A") is None

        # Client B should see only job for Client B
        job_b = bridge.get_job(client_id="client_B")
        assert job_b is not None
        assert job_b["url"] == "https://www.facebook.com/api/graphql/test_b"
        assert job_b["client_id"] == "client_B"

        # Client B queue is now empty
        assert bridge.get_job(client_id="client_B") is None

        # Complete jobs
        bridge.complete_job(job_a["id"], {"status_code": 200, "text": "result_a"}, client_id="client_A")
        bridge.complete_job(job_b["id"], {"status_code": 200, "text": "result_b"}, client_id="client_B")

        res_a = await task_a
        res_b = await task_b

        assert res_a["text"] == "result_a"
        assert res_b["text"] == "result_b"

    asyncio.run(_run())


def test_bridge_rejects_non_graphql_urls():
    """Verify that ExtensionBridge immediately rejects non-GraphQL URLs to protect against checkpoints."""
    async def _run():
        bridge = ExtensionBridge()
        res = await bridge.execute_request("https://www.facebook.com/groups/123/posts/456", client_id="test")
        assert res["status"] == "error"
        assert res["status_code"] == 403
        assert "Only /api/graphql/" in res["error"]

    asyncio.run(_run())


def test_multitenant_heartbeat_isolation():
    """Verify heartbeat connection status is isolated per client_id."""
    bridge = ExtensionBridge()

    # Initially neither is connected
    assert not bridge.is_connected("tenant_1")
    assert not bridge.is_connected("tenant_2")

    # Tenant 1 polls for jobs
    bridge.get_job("tenant_1")

    # Tenant 1 is now connected, Tenant 2 remains disconnected
    assert bridge.is_connected("tenant_1")
    assert not bridge.is_connected("tenant_2")


def test_backward_compatibility():
    """Verify default client_id works with legacy properties."""
    bridge = ExtensionBridge()

    assert not bridge.has_jobs("default")
    assert not bridge.is_connected("default")

    bridge.get_job("default")
    assert bridge.is_connected("default")
    assert bridge.is_connected()  # default arg
