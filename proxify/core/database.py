import asyncpg
import logging
import os
from typing import Optional

logger = logging.getLogger("proxify.core.database")

class DatabaseManager:
    """Manages the asyncpg connection pool and core schemas."""
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        
    async def connect(self, dsn: str, min_size: int = 5, max_size: int = 20):
        """Initializes the asyncpg connection pool."""
        logger.info(f"Connecting to Database pool (min={min_size}, max={max_size})...")
        self.pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=60,
            server_settings={
                'application_name': 'proxify_core',
                'timezone': 'UTC'
            }
        )
        await self._init_core_schema()
        logger.info("Database pool established and core schema verified.")
        
    async def disconnect(self):
        """Closes the connection pool."""
        if self.pool:
            logger.info("Closing Database pool...")
            await self.pool.close()
            self.pool = None

    async def _init_core_schema(self):
        """Creates the core schema and raw_payloads table for offline processing."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("CREATE SCHEMA IF NOT EXISTS core;")
                
                # The single ingestion point for all high-speed proxy traffic
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS core.raw_payloads (
                        id BIGSERIAL PRIMARY KEY,
                        topic VARCHAR(255) NOT NULL,
                        raw_data JSONB NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        processed BOOLEAN DEFAULT FALSE
                    );
                """)
                
                # Index for the background worker to quickly find unprocessed payloads
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_raw_payloads_processed 
                    ON core.raw_payloads(processed) 
                    WHERE processed = FALSE;
                """)
