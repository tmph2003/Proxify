import asyncio
import logging
import json
from pathlib import Path
from proxify.core.database import DatabaseManager

logger = logging.getLogger("proxify.core.worker")

class BackgroundWorker:
    """
    Offline Data Normalizer (CQRS Architecture).
    Reads from core.raw_payloads and processes the events.
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._is_running = False
        self._worker_task = None
        self.token_file = Path(__file__).parent.parent / "platforms" / "facebook" / "tokens.json"

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
        # Fetch up to 100 unprocessed payloads
        async with self.db_manager.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT id, topic, raw_data 
                FROM core.raw_payloads 
                WHERE processed = FALSE 
                ORDER BY id ASC LIMIT 100
            """)
            
            if not records:
                return

            processed_ids = []
            
            for record in records:
                try:
                    payload = json.loads(record['raw_data'])
                    if record['topic'] == 'facebook.graphql.request':
                        await self._handle_fb_graphql(payload)
                    elif record['topic'] == 'facebook.graphql.response':
                        await self._handle_fb_graphql_response(payload)
                    elif record['topic'] == 'facebook.post.status':
                        await self._handle_fb_status(conn, payload)
                        
                    processed_ids.append(record['id'])
                except Exception as e:
                    logger.error(f"Error processing payload {record['id']}: {e}")
                    # Mark as processed anyway to avoid poison pill loop, 
                    # but in production we'd move it to a dead-letter queue.
                    processed_ids.append(record['id'])

            if processed_ids:
                # Mark as processed
                await conn.execute("""
                    UPDATE core.raw_payloads 
                    SET processed = TRUE 
                    WHERE id = ANY($1::bigint[])
                """, (processed_ids,))
                logger.info(f"Processed {len(processed_ids)} raw payloads.")

    async def _handle_fb_graphql_response(self, payload: dict):
        """Offline normalization of Facebook GraphQL responses."""
        raw_json = payload.get("raw_json")
        if not raw_json:
            return
            
        # We delegate the heavy parsing to a separate thread so we don't block the worker loop
        # and we reuse the legacy extractor logic.
        def _parse_and_insert():
            from proxify.platforms.facebook.extractor import extract_from_responses
            # extract_from_responses expects a list of stringified JSON lines
            lines = raw_json.split("\n")
            p_count, c_count, detected_group = extract_from_responses(
                lines, 
                vars_dict={}, # We might need to store request vars too, but let's try without first
            )
            if p_count > 0 or c_count > 0:
                logger.info(f"Worker Extracted: {p_count} posts, {c_count} comments (Group: {detected_group})")
                
        await asyncio.to_thread(_parse_and_insert)

    async def _handle_fb_graphql(self, payload: dict):
        """Updates the saved GraphQL tokens IN MEMORY ONLY."""
        friendly_name = payload.get("friendly_name", "")
        if not friendly_name:
            return
            
        try:
            from proxify.platforms.facebook.token_store import IN_MEMORY_TEMPLATES
            
            tokens = {
                "headers": payload.get("headers", {}),
                "form_data": payload.get("form_data", {})
            }
            
            if "GroupsCometFeed" in friendly_name:
                IN_MEMORY_TEMPLATES["feed"] = tokens
                IN_MEMORY_TEMPLATES["headers"] = tokens["headers"]
                IN_MEMORY_TEMPLATES["form_data"] = tokens["form_data"]
                logger.info(f"Worker: Updated Facebook Feed Template IN MEMORY! ({friendly_name})")
            elif "comment" in friendly_name.lower() or "ufi" in friendly_name.lower():
                if "repl" in friendly_name.lower():
                    IN_MEMORY_TEMPLATES["reply"] = tokens
                    logger.info(f"Worker: Updated Facebook Reply Template IN MEMORY! ({friendly_name})")
                else:
                    IN_MEMORY_TEMPLATES["comment"] = tokens
                    logger.info(f"Worker: Updated Facebook Comment Template IN MEMORY! ({friendly_name})")
        except Exception as e:
            logger.error(f"Template parsing error in worker: {e}")

    async def _handle_fb_status(self, conn, payload: dict):
        """Updates post status to inactive."""
        path = payload.get("path")
        is_active = payload.get("is_active")
        if not path:
            return
            
        # Extract base path and ignore query params to match permalink
        permalink_pattern = f"%{path.rstrip('/')}%"
        
        # Note: facebook.posts still uses synchronous psycopg2 elsewhere, but asyncpg here is fine.
        result = await conn.execute("""
            UPDATE facebook.posts 
            SET is_active = $1 
            WHERE permalink_url LIKE $2
        """, is_active, permalink_pattern)
        
        # asyncpg execute returns a status string like "UPDATE 1"
        if result and result.startswith("UPDATE "):
            count = int(result.split()[1])
            if count > 0:
                logger.info(f"Worker: Marked {count} post(s) as inactive from {path}")
