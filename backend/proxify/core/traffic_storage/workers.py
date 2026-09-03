import logging
import queue
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger("proxify.core.traffic_storage.workers")
_COMMIT_BATCH_SIZE = 50  # Hardcoded or imported, but we can set a default

class BackgroundWorker(ABC):
    """Template method pattern for background workers."""
    
    def __init__(self, pool, repository, name="Worker"):
        self.pool = pool
        self.repository = repository
        self.name = name
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name=name)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def join(self, timeout=2.0):
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_loop(self):
        self.on_start()
        while not self._stop_event.is_set():
            try:
                self.do_work()
            except Exception as e:
                logger.error(f"[{self.name}] Error: {e}")
        self.on_stop()

    def on_start(self):
        pass
        
    def on_stop(self):
        pass

    @abstractmethod
    def do_work(self):
        """Must be implemented by subclasses."""
        pass


class TTLWorker(BackgroundWorker):
    """Deletes requests older than 3 days."""
    
    def __init__(self, pool, repository):
        super().__init__(pool, repository, name="TTL Worker")
        self._first_run = True

    def do_work(self):
        if self._first_run:
            # Wait 1 minute before first run to let the app warm up
            if self._stop_event.wait(60):
                return
            self._first_run = False
        else:
            # Sleep for an hour, waking up early if stop is requested
            if self._stop_event.wait(3600):
                return

        if self._stop_event.is_set():
            return

        conn = self.pool.get_connection()
        try:
            with conn:
                deleted_count = self.repository.delete_old_requests(conn)
                if deleted_count > 0:
                    logger.info(f"[{self.name}] Cleaned up {deleted_count} old requests.")
        finally:
            self.pool.release_connection(conn)


class AsyncWriterWorker(BackgroundWorker):
    """Reads from a queue and batches inserts."""
    
    def __init__(self, pool, repository, batch_size=_COMMIT_BATCH_SIZE):
        super().__init__(pool, repository, name="Writer")
        self.write_queue = queue.Queue(maxsize=5000)
        self.batch_size = batch_size
        self._batch = []
        self._callbacks = []

    def enqueue(self, data, callback=None):
        try:
            self.write_queue.put_nowait((data, callback))
        except queue.Full:
            logger.warning("[Storage] Write queue is full (Backpressure). Dropping request data to save RAM.")

    def flush(self):
        self.write_queue.join()

    def do_work(self):
        # Wait for items to arrive
        while len(self._batch) < self.batch_size:
            timeout = 1.0 if not self._batch else 0.1
            try:
                item = self.write_queue.get(timeout=timeout)
                data, callback = item
                self._batch.append(data)
                self._callbacks.append(callback)
            except queue.Empty:
                break
        
        if not self._batch:
            return  # Will just loop again if stop event isn't set
        
        conn = self.pool.get_connection()
        try:
            with conn:
                self.repository.save_requests_batch(conn, self._batch, self._callbacks)
        except Exception as e:
            logger.error(f"[{self.name}] Error bulk saving requests: {e}")
        finally:
            self.pool.release_connection(conn)
            for _ in self._batch:
                self.write_queue.task_done()
            
            self._batch.clear()
            self._callbacks.clear()

    def on_stop(self):
        """Ensure we try to clear out the batch on stop if possible."""
        pass
