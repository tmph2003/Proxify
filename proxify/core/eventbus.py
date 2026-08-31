import asyncio
import logging
import time
from typing import Any, List, Dict
import asyncpg

logger = logging.getLogger("proxify.core.eventbus")

class AsyncEventBus:
    """
    High-performance Event Bus with Backpressure and Micro-batching.
    Used to decouple real-time proxy traffic from heavy Database IO.
    """
    def __init__(self, db_pool: asyncpg.Pool, max_queue_size: int = 5000, batch_size: int = 500, flush_interval: float = 1.0):
        self.queue = asyncio.Queue(maxsize=max_queue_size)
        self.db_pool = db_pool
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._consumer_task = None
        self._is_running = False

    def start(self):
        """Starts the background consumer loop."""
        if not self._is_running:
            self._is_running = True
            self._consumer_task = asyncio.create_task(self._consumer_loop())

    async def stop(self):
        """Gracefully shuts down the bus, flushing remaining events."""
        self._is_running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        
        # Flush whatever is left in the queue
        remaining = []
        while not self.queue.empty():
            try:
                remaining.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
                
        if remaining:
            await self._bulk_insert(remaining)

    def publish(self, topic: str, data: dict):
        """
        Publishes an event to the bus. Uses load shedding if the queue is full.
        """
        event = {"topic": topic, "data": data, "timestamp": time.time()}
        try:
            # We use put_nowait to NEVER block the mitmproxy loop.
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # TCP Backpressure fallback: Drop event to save memory and avoid freezing proxy.
            # In a critical setup, we would spool to SQLite here.
            logger.critical(f"EventBus Queue Full! Dropping event on topic {topic} to prevent OOM.")

    async def _consumer_loop(self):
        """Background task that batches events and flushes them to the DB."""
        batch = []
        
        while self._is_running:
            try:
                # Wait for an item, but wake up periodically to flush
                item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                batch.append(item)
                self.queue.task_done()
            except asyncio.TimeoutError:
                # Timeout reached, time to flush if we have anything
                pass
            except asyncio.CancelledError:
                break
                
            if len(batch) >= self.batch_size or (batch and self.queue.empty()):
                await self._bulk_insert(batch)
                batch.clear()

    async def _bulk_insert(self, batch: List[Dict[str, Any]]):
        """Performs a bulk insert of the batch into the raw_payloads table."""
        if not batch:
            return
            
        try:
            import json
            # Prepare records for asyncpg (must match columns: topic, data, created_at)
            records = [(item['topic'], json.dumps(item['data']), item['timestamp']) for item in batch]
            
            # Use executemany for now. For absolute max speed, copy_records_to_table is better.
            async with self.db_pool.acquire() as conn:
                await conn.executemany(
                    "INSERT INTO core.raw_payloads (topic, raw_data, created_at) VALUES ($1, $2, to_timestamp($3))",
                    records
                )
            logger.debug(f"Flushed batch of {len(batch)} events to DB.")
        except Exception as e:
            logger.error(f"Failed to bulk insert {len(batch)} events: {e}")
            # Fallback strategy: In a real system, we would chop the batch in half and retry
            # to isolate the single bad record that caused the failure.
