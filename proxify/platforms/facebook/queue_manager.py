"""
Facebook Crawler - Persistent Queue Manager
===========================================
Manages tasks for crawling and refreshing using SQLite (via aiosqlite).
Ensures zero data loss and simple setup (no Redis required).
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import aiosqlite

logger = logging.getLogger("proxify.facebook.queue")


class SQLiteQueueManager:
    """Persistent task queue backed by SQLite."""
    
    def __init__(self, db_path: str = "queue.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        
    async def init_db(self):
        """Initialize the queue table and reset processing tasks."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    retries INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    status TEXT DEFAULT 'pending',
                    created_at REAL,
                    updated_at REAL
                )
            ''')
            await db.commit()
            
            # Reset 'processing' tasks back to 'pending' in case of a crash
            await db.execute("UPDATE queue SET status = 'pending' WHERE status = 'processing'")
            await db.commit()

    async def put(self, task_type: str, payload: Dict[str, Any], max_retries: int = 3):
        """Enqueue a new task."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            payload_str = json.dumps(payload)
            now = time.time()
            await db.execute('''
                INSERT INTO queue (task_type, payload, max_retries, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (task_type, payload_str, max_retries, now, now))
            await db.commit()

    async def get(self) -> Optional[Dict[str, Any]]:
        """
        Dequeue a task. Returns None if queue is empty.
        In a worker loop, you should sleep briefly if this returns None.
        """
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Fetch oldest pending task
            async with db.execute("SELECT * FROM queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1") as cursor:
                row = await cursor.fetchone()
                if row:
                    # Mark as processing
                    await db.execute("UPDATE queue SET status = 'processing', updated_at = ? WHERE id = ?", (time.time(), row['id']))
                    await db.commit()
                    return {
                        "id": row['id'],
                        "type": row['task_type'],
                        "payload": json.loads(row['payload']),
                        "retries": row['retries'],
                        "max_retries": row['max_retries']
                    }
        return None
        
    async def task_done(self, task_id: int):
        """Mark a task as successfully completed."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE queue SET status = 'completed', updated_at = ? WHERE id = ?", (time.time(), task_id))
            await db.commit()
            
    async def retry_task(self, task_id: int, reason: str):
        """Re-enqueue a task if it hasn't exceeded max_retries. Otherwise, mark as failed (DLQ)."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT retries, max_retries FROM queue WHERE id = ?", (task_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return
                
                retries = row['retries'] + 1
                max_retries = row['max_retries']
                
                if retries <= max_retries:
                    logger.warning(f"Retrying task {task_id} (Attempt {retries}/{max_retries}): {reason}")
                    await db.execute("UPDATE queue SET status = 'pending', retries = ?, updated_at = ? WHERE id = ?", 
                                     (retries, time.time(), task_id))
                else:
                    logger.error(f"Task {task_id} failed after {max_retries} retries: {reason}. Moving to DLQ (status='failed').")
                    await db.execute("UPDATE queue SET status = 'failed', updated_at = ? WHERE id = ?", 
                                     (time.time(), task_id))
            await db.commit()
            
    async def get_progress(self) -> dict:
        """Get counts of tasks grouped by status."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, count(*) as cnt FROM queue GROUP BY status") as cursor:
                rows = await cursor.fetchall()
                stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "total": 0}
                for row in rows:
                    status = row[0]
                    cnt = row[1]
                    stats[status] = cnt
                    stats["total"] += cnt
                return stats
                
    async def clear(self):
        """Clear all tasks."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM queue")
            await db.commit()
