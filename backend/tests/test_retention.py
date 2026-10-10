import time
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from proxify.core.traffic_storage import parse_retention_days
from proxify.core.traffic_storage.repository import RequestRepository
from proxify.core.traffic_storage.workers import TTLWorker
from proxify.dashboard import Dashboard


def test_parse_retention_days():
    # Standard numbers
    assert parse_retention_days(7) == 7
    assert parse_retention_days(7.5) == 7
    
    # Strings with various formats
    assert parse_retention_days("7") == 7
    assert parse_retention_days("7 days") == 7
    assert parse_retention_days("7d") == 7
    assert parse_retention_days("14 Days") == 14
    assert parse_retention_days("30-days") == 30
    
    # Defaults and edge cases
    assert parse_retention_days(None, default=7) == 7
    assert parse_retention_days("invalid", default=7) == 7
    assert parse_retention_days("", default=7) == 7
    assert parse_retention_days(0) == 1
    assert parse_retention_days(-5) == 1


def test_repository_delete_old_requests_parameterized():
    repo = RequestRepository()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 42
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Test default 7 days retention
    now_epoch = 1700000000.0
    with patch("time.time", return_value=now_epoch):
        deleted = repo.delete_old_requests(mock_conn, retention_days=7)

    assert deleted == 42
    expected_cutoff = now_epoch - (7 * 86400.0)
    
    # Check that cursor.execute was called with parameterized query
    execute_calls = mock_cur.execute.call_args_list
    assert len(execute_calls) >= 1
    
    # First call must be the requests table deletion
    query, params = execute_calls[0][0]
    assert "DELETE FROM requests" in query
    assert "timestamp_epoch < %s" in query
    assert params == (expected_cutoff,)


def test_repository_delete_old_requests_backwards_compatible():
    repo = RequestRepository()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 10
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    now_epoch = 1700000000.0
    with patch("time.time", return_value=now_epoch):
        # Pass legacy interval string "3 days"
        deleted = repo.delete_old_requests(mock_conn, interval="3 days")

    assert deleted == 10
    expected_cutoff = now_epoch - (3 * 86400.0)
    query, params = mock_cur.execute.call_args_list[0][0]
    assert params == (expected_cutoff,)


def test_ttl_worker_passes_configured_retention():
    mock_pool = MagicMock()
    mock_repo = MagicMock()
    mock_conn = MagicMock()
    mock_pool.get_connection.return_value = mock_conn
    mock_repo.delete_old_requests.return_value = 15

    worker = TTLWorker(mock_pool, mock_repo, retention_days=7)
    assert worker.retention_days == 7

    # Bypass sleep and run one iteration of work
    worker._first_run = False
    with patch.object(worker._stop_event, "wait", return_value=False):
        worker.do_work()

    mock_repo.delete_old_requests.assert_called_once_with(mock_conn, retention_days=7)
    mock_pool.release_connection.assert_called_once_with(mock_conn)


@pytest.mark.anyio
async def test_dashboard_config_endpoints_retention():
    mock_storage = MagicMock()
    mock_storage.db_integration_enabled = True
    mock_storage.db_allowed_domains = ["example.com"]
    mock_storage.retention_days = 7
    mock_storage.ttl_worker = MagicMock()
    mock_storage.ttl_worker.retention_days = 7

    server = Dashboard(storage=mock_storage, port=8888)

    # 1. Test GET /api/config
    get_req = make_mocked_request("GET", "/api/config")
    get_resp = await server._handle_get_config(get_req)
    assert get_resp.status == 200
    import json
    data = json.loads(get_resp.text)
    assert data["retention_days"] == 7
    assert data["db_integration_enabled"] is True

    # 2. Test POST /api/toggle_db with updated retention_days
    post_req = make_mocked_request("POST", "/api/toggle_db")
    post_req.json = AsyncMock(return_value={"retention_days": 14})
    post_resp = await server._handle_toggle_db(post_req)
    assert post_resp.status == 200
    resp_data = json.loads(post_resp.text)
    assert resp_data["retention_days"] == 14
    assert mock_storage.retention_days == 14
    assert mock_storage.ttl_worker.retention_days == 14
