import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest

from proxify.database.connection import DatabasePool
from proxify.core.traffic_storage import RequestStorage
from proxify.core.traffic_storage.repository import RequestRepository
from proxify.core.traffic_storage.workers import AsyncWriterWorker, TTLWorker


def _sample_request_tuple(i: int = 1) -> tuple:
    now_str = "2026-11-16T18:00:00Z"
    now_epoch = 1700000000.0 + i
    return (
        now_str,
        now_epoch,
        "GET",
        f"https://example.com/api/{i}",
        "https",
        "example.com",
        443,
        f"/api/{i}",
        "",
        '{"host": "example.com"}',
        "",
        "application/json",
        200,
        '{"content-type": "application/json"}',
        f'{{"item": {i}}}',
        "application/json",
        len(f'{{"item": {i}}}'),
        12.5,
        0,
        "",
        "",
        "",
    )


def test_batch_writes_vectorized_returning_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_batch.db")
        pool = DatabasePool(db_path=db_path)
        repo = RequestRepository()

        with pool.connection() as conn:
            repo.init_db(conn)

        batch_size = 50
        batch = [_sample_request_tuple(i) for i in range(batch_size)]
        callback_ids = []

        def make_cb(expected_idx):
            def cb(row_id):
                callback_ids.append((expected_idx, row_id))
            return cb

        callbacks = [make_cb(i) for i in range(batch_size)]

        with pool.connection() as conn:
            returned_ids = repo.save_requests_batch(conn, batch, callbacks)

        assert len(returned_ids) == batch_size
        assert returned_ids == list(range(1, batch_size + 1))
        assert len(callback_ids) == batch_size
        for idx, (expected_idx, row_id) in enumerate(callback_ids):
            assert expected_idx == idx
            assert row_id == idx + 1

        # Verify all 50 items exist in DB
        requests = repo.query_requests(pool, domain="example.com", limit=100)
        assert len(requests) == batch_size

        pool.close()


def test_callbacks_executed_outside_write_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_cb_lock.db")
        pool = DatabasePool(db_path=db_path)
        repo = RequestRepository()

        with pool.connection() as conn:
            repo.init_db(conn)

        worker = AsyncWriterWorker(pool, repo, batch_size=5)
        lock_was_held = []

        def callback(row_id):
            # Check whether writer lock is held by the worker during callback invocation
            # In threading.RLock, _is_owned() indicates if current thread holds the lock
            is_locked = pool._lock._is_owned() if hasattr(pool._lock, "_is_owned") else pool._lock.locked()
            lock_was_held.append(is_locked)

        for i in range(5):
            worker.enqueue(_sample_request_tuple(i), callback=callback)

        worker.do_work()

        assert len(lock_was_held) == 5
        # Callbacks MUST be executed outside write lock
        assert all(held is False for held in lock_was_held)

        pool.close()


def test_read_connection_wal_concurrency():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_wal_conc.db")
        pool = DatabasePool(db_path=db_path)
        repo = RequestRepository()

        try:
            with pool.connection() as conn:
                repo.init_db(conn)
                repo.save_request(conn, _sample_request_tuple(1))

            # Writer starts transaction and inserts uncommitted row
            writer_ready = threading.Event()
            writer_can_commit = threading.Event()
            writer_done = threading.Event()

            def writer_thread():
                with pool.connection() as conn:
                    conn.execute("BEGIN IMMEDIATE;")
                    repo.save_request(conn, _sample_request_tuple(2))
                    writer_ready.set()
                    writer_can_commit.wait(timeout=5.0)
                    conn.commit()
                writer_done.set()

            t_writer = threading.Thread(target=writer_thread, daemon=True)
            t_writer.start()

            writer_ready.wait(timeout=5.0)

            # Reader reads via read_connection while writer holds active uncommitted transaction
            # In WAL mode, this must not block and must see previously committed rows
            t_start = time.perf_counter()
            with pool.read_connection() as r_conn:
                cur = r_conn.execute("SELECT COUNT(*) FROM requests")
                count = cur.fetchone()[0]
            elapsed = time.perf_counter() - t_start

            assert count == 1  # Sees committed snapshot, not uncommitted
            assert elapsed < 1.0  # Zero lock wait delay

            # Release writer to commit
            writer_can_commit.set()
            writer_done.wait(timeout=5.0)

            # Now reader sees both rows
            with pool.read_connection() as r_conn:
                cur = r_conn.execute("SELECT COUNT(*) FROM requests")
                count_after = cur.fetchone()[0]

            assert count_after == 2
        finally:
            writer_can_commit.set()
            if 't_writer' in locals():
                t_writer.join(timeout=2.0)
            pool.close()


def test_database_pool_pragmas_and_reader_pooling():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_pragmas.db")
        pool = DatabasePool(db_path=db_path)

        with pool.connection() as w_conn:
            assert w_conn.execute("PRAGMA journal_mode;").fetchone()[0].lower() == "wal"
            assert w_conn.execute("PRAGMA synchronous;").fetchone()[0] == 1  # NORMAL
            assert w_conn.execute("PRAGMA cache_size;").fetchone()[0] == -64000
            assert w_conn.execute("PRAGMA temp_store;").fetchone()[0] == 2  # MEMORY
            assert w_conn.execute("PRAGMA mmap_size;").fetchone()[0] == 268435456

        with pool.read_connection() as r_conn:
            assert r_conn.execute("PRAGMA query_only;").fetchone()[0] == 1
            assert r_conn.execute("PRAGMA cache_size;").fetchone()[0] == -64000
            assert r_conn.execute("PRAGMA temp_store;").fetchone()[0] == 2  # MEMORY
            assert r_conn.execute("PRAGMA mmap_size;").fetchone()[0] == 268435456

        pool.close()


def test_database_pool_concurrent_close_and_reopen_thread_safety():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_close_conc.db")
        pool = DatabasePool(db_path=db_path)
        repo = RequestRepository()

        with pool.connection() as conn:
            repo.init_db(conn)

        stop_event = threading.Event()
        errors = []

        def worker_reader(worker_id):
            while not stop_event.is_set():
                try:
                    with pool.read_connection() as conn:
                        cur = conn.execute("SELECT COUNT(*) FROM requests")
                        cur.fetchone()
                except Exception as e:
                    errors.append((worker_id, e))
                time.sleep(0.005)

        def worker_writer(worker_id):
            while not stop_event.is_set():
                try:
                    with pool.connection() as conn:
                        repo.save_request(conn, _sample_request_tuple(worker_id))
                except Exception as e:
                    errors.append((worker_id, e))
                time.sleep(0.01)

        threads = []
        for i in range(4):
            t = threading.Thread(target=worker_reader, args=(f"r_{i}",), daemon=True)
            threads.append(t)
            t.start()

        for i in range(2):
            t = threading.Thread(target=worker_writer, args=(i,), daemon=True)
            threads.append(t)
            t.start()

        # Perform pool resets while workers are running
        time.sleep(0.1)
        pool.close()
        time.sleep(0.1)
        pool.close()
        time.sleep(0.1)

        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)

        pool.close()
        assert len(errors) == 0, f"Encountered unexpected concurrency errors: {errors}"


def test_read_queries_decoupled_from_write_queue():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_decoupled.db")
        pool = DatabasePool(db_path=db_path)
        repo = RequestRepository()

        with pool.connection() as conn:
            repo.init_db(conn)

        # Mock pool on RequestStorage
        from unittest.mock import patch
        with patch("proxify.core.traffic_storage.shared_pool", pool):
            storage = RequestStorage()
            storage.db_integration_enabled = True

            # Enqueue an item into async_writer
            storage.save_request_async({"url": "https://example.com/test", "method": "GET"})

            # Query should not block on flush
            stats = storage.get_stats()
            assert isinstance(stats, dict)
            domains = storage.get_domains()
            assert isinstance(domains, list)
            reqs = storage.query_requests()
            assert isinstance(reqs, list)

            storage.close()
            pool.close()
