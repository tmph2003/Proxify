import asyncio
import logging
import json
from pathlib import Path
from proxify.core.database import DatabaseManager

logger = logging.getLogger("proxify.core.worker")

class BackgroundWorker:
    """
    Offline Data Normalizer (CQRS Architecture).
    Reads from core_raw_payloads and dispatches events to registered topic handlers.

    Migrated from asyncpg to aiosqlite.
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._is_running = False
        self._worker_task = None
        self._topic_handlers = {}

    def register_topic_handler(self, topic: str, handler):
        """Register an async handler `(payload, conn) -> None` for a given topic."""
        self._topic_handlers[topic] = handler
        logger.debug(f"Registered worker handler for topic: {topic}")

    def start(self):
        if not self._is_running:
            self._is_running = True
            self._worker_task = asyncio.create_task(self._run_loop())
            logger.info("Background Worker started.")

    async def stop(self):
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Background Worker stopped.")

    async def _run_loop(self):
        while self._is_running:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
            
            # Poll every 2 seconds
            await asyncio.sleep(2.0)

    async def _process_batch(self):
        if not self.db_manager.pool:
            return

        try:
            # Fetch up to 100 unprocessed payloads
            async with self.db_manager.acquire() as conn:
                records = await conn.fetch("""
                    SELECT id, topic, raw_data 
                    FROM core_raw_payloads 
                    WHERE processed = 0 
                    ORDER BY id ASC LIMIT 100
                """)
                
                if not records:
                    return

                processed_ids = []
                
                for record in records:
                    try:
                        payload = json.loads(record['raw_data'])
                        topic = record['topic']
                        handler = self._topic_handlers.get(topic)
                        if handler is not None:
                            await handler(payload, conn)
                        processed_ids.append(record['id'])
                    except Exception as e:
                        logger.error(f"Error processing payload {record['id']}: {e}")
                        processed_ids.append(record['id'])

                if processed_ids:
                    # SQLite doesn't support ANY($1::bigint[]), use IN clause
                    placeholders = ','.join(['?'] * len(processed_ids))
                    await conn.execute(f"""
                        UPDATE core_raw_payloads 
                        SET processed = 1 
                        WHERE id IN ({placeholders})
                    """, *processed_ids)
                    logger.info(f"Processed {len(processed_ids)} raw payloads.")
        except Exception as e:
            logger.error(f"Worker batch processing error: {e}")
