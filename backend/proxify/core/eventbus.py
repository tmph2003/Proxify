import asyncio
import logging
import time
import json
from typing import Any, List, Dict

logger = logging.getLogger("proxify.core.eventbus")

class AsyncEventBus:
    """
    High-performance Event Bus with Backpressure and Micro-batching.
    Used to decouple real-time proxy traffic from heavy Database IO.

    Migrated from asyncpg to aiosqlite.
    """
    def __init__(self, db_pool, max_queue_size: int = 5000, batch_size: int = 500, flush_interval: float = 1.0):
        self.queue = asyncio.Queue(maxsize=max_queue_size)
        self.db_pool = db_pool  # aiosqlite.Connection (from DatabaseManager)
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
        """Performs a bulk insert of the batch into the core_raw_payloads table."""
        if not batch:
            return

        if not self.db_pool:
            logger.warning("Database pool is closed or unavailable. Skipping bulk insert.")
            return

        try:
            # Prepare records for aiosqlite
            records = [
                (item['topic'], json.dumps(item['data']), 
                 time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(item['timestamp'])))
                for item in batch
            ]
            
            await self.db_pool.executemany(
                "INSERT INTO core_raw_payloads (topic, raw_data, created_at) VALUES (?, ?, ?)",
                records
            )
            await self.db_pool.commit()
            logger.debug(f"Flushed batch of {len(batch)} events to DB.")
        except Exception as e:
            logger.error(f"Failed to bulk insert {len(batch)} events: {e}")
