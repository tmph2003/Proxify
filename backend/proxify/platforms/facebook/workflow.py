"""
Facebook Workflow & Task Orchestration Engine.
=============================================
Module này quản lý toàn bộ vòng đời điều phối tác vụ cào dữ liệu:
1. Command Pattern: Đóng gói các yêu cầu cào (CrawlFeedCommand, CrawlCommentCommand, RefreshCommand)
2. Observer Pattern: Theo dõi và cập nhật tiến độ cào dữ liệu (CrawlerStateObserver, state_observer)
3. Task Queue: Hàng đợi tác vụ bền vững bất đồng bộ với SQLite và Dead-Letter Queue (SQLiteQueueManager)
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

logger = logging.getLogger("proxify.facebook.workflow")


# ─── 1. Command Pattern (Đóng Gói Lệnh Cào) ───────────────────────────────────

class BaseCommand(ABC):
    """Command Pattern: Encapsulates a crawl request as an object."""
    @abstractmethod
    async def execute(self):
        pass


class RefreshCommand(BaseCommand):
    """Lệnh làm mới tương tác cho danh sách link bài viết."""
    def __init__(self, receiver, urls: List[str], template: dict = None, client_cookie: str = None):
        self.receiver = receiver
        self.urls = urls
        self.template = template
        self.client_cookie = client_cookie

    async def execute(self):
        logger.info(f"[Command] Executing RefreshCommand for {len(self.urls)} posts")
        await self.receiver._execute_crawl_specific_posts(self.urls, self.template, self.client_cookie)


class CrawlFeedCommand(BaseCommand):
    """Lệnh cào bảng tin nhóm Facebook theo khoảng thời gian và cursor."""
    def __init__(self, receiver, group_id: str, start_ts: int, end_ts: int,
                 template: dict = None, client_cookie: str = None, reset_cursor: bool = True):
        self.receiver = receiver
        self.group_id = group_id
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.template = template
        self.client_cookie = client_cookie
        self.reset_cursor = reset_cursor

    async def execute(self):
        logger.info(f"[Command] Executing CrawlFeedCommand for group {self.group_id}")
        await self.receiver._execute_crawl_group_feed(
            self.group_id, self.start_ts, self.end_ts, self.template, self.client_cookie, self.reset_cursor
        )


class CrawlCommentCommand(BaseCommand):
    """Lệnh cào bình luận cho một bài viết cụ thể."""
    def __init__(self, receiver, post_id: str, feedback_id: str,
                 template: dict = None, client_cookie: str = None):
        self.receiver = receiver
        self.post_id = post_id
        self.feedback_id = feedback_id
        self.template = template
        self.client_cookie = client_cookie

    async def execute(self):
        logger.info(f"[Command] Executing CrawlCommentCommand for post {self.post_id}")
        await self.receiver._execute_crawl_comments(
            self.post_id, self.feedback_id, self.template, self.client_cookie
        )


class CrawlProfileFeedCommand(BaseCommand):
    """Lệnh cào bảng tin trang cá nhân Facebook theo khoảng thời gian."""
    def __init__(self, receiver, profile_id: str, start_ts: int, end_ts: int,
                 template: dict = None, client_cookie: str = None):
        self.receiver = receiver
        self.profile_id = profile_id
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.template = template
        self.client_cookie = client_cookie

    async def execute(self):
        logger.info(f"[Command] Executing CrawlProfileFeedCommand for profile {self.profile_id}")
        await self.receiver._execute_crawl_profile_feed(
            self.profile_id, self.start_ts, self.end_ts, self.template, self.client_cookie
        )


# ─── 2. Observer Pattern (Giám Sát Trạng Thái & Tiến Độ) ──────────────────────

class CrawlerStateObserver:
    """Observer Pattern: Quản lý trạng thái và tiến độ cào độc lập,
    không làm gắn kết chặt chẽ với logic coroutine cào.
    """
    def __init__(self):
        self.crawl_state = {"status": "idle", "group_id": "", "message": ""}
        self.refresh_progress = {"total": 0, "current": 0, "status": "idle"}
        self._comment_progress = {}

    def update_crawl_state(self, status: str = None, message: str = None, group_id: str = None):
        if status:
            self.crawl_state["status"] = status
        if message:
            self.crawl_state["message"] = message
        if group_id:
            self.crawl_state["group_id"] = group_id

    def reset_refresh_progress(self, total: int):
        self.refresh_progress.update(total=total, current=0, status="running")

    def increment_refresh_progress(self):
        self.refresh_progress["current"] += 1
        if self.refresh_progress["current"] >= self.refresh_progress["total"]:
            self.refresh_progress["status"] = "idle"

    def set_refresh_status(self, status: str):
        self.refresh_progress["status"] = status

    def update_comment_progress(self, post_id: str, status: str, message: str, count: int = 0):
        if post_id not in self._comment_progress:
            self._comment_progress[post_id] = {"status": "idle", "total": 0, "message": ""}

        self._comment_progress[post_id].update({
            "status": status,
            "message": message,
            "total": self._comment_progress[post_id].get("total", 0) + count
        })

    def get_comment_progress(self, post_id: str):
        return self._comment_progress.get(post_id)


# Global Observer Instance
state_observer = CrawlerStateObserver()


# ─── 3. Persistent Queue Manager (Hàng Đợi SQLite & DLQ) ─────────────────────

class SQLiteQueueManager:
    """Hàng đợi tác vụ bền vững bất đồng bộ dựa trên SQLite (aiosqlite)."""

    def __init__(self, db_path: str = "queue.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init_db(self):
        """Khởi tạo bảng queue và tự động phục hồi các task dở dang."""
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

            # Tự động reset task 'processing' về 'pending' khi khởi động lại ứng dụng
            await db.execute("UPDATE queue SET status = 'pending' WHERE status = 'processing'")
            await db.commit()

    async def put(self, task_type: str, payload: Dict[str, Any], max_retries: int = 3):
        """Đưa task mới vào hàng đợi."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            payload_str = json.dumps(payload)
            now = time.time()
            await db.execute('''
                INSERT INTO queue (task_type, payload, max_retries, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (task_type, payload_str, max_retries, now, now))
            await db.commit()

    async def get(self) -> Optional[Dict[str, Any]]:
        """Lấy task pending cũ nhất (FIFO)."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1") as cursor:
                row = await cursor.fetchone()
                if row:
                    await db.execute(
                        "UPDATE queue SET status = 'processing', updated_at = ? WHERE id = ?",
                        (time.time(), row['id'])
                    )
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
        """Đánh dấu hoàn thành task."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE queue SET status = 'completed', updated_at = ? WHERE id = ?", (time.time(), task_id))
            await db.commit()

    async def retry_task(self, task_id: int, reason: str):
        """Thử lại task nếu chưa vượt quá max_retries, ngược lại đưa vào DLQ ('failed')."""
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
                    logger.error(f"Task {task_id} failed after {max_retries} retries: {reason}. Moving to DLQ.")
                    await db.execute("UPDATE queue SET status = 'failed', updated_at = ? WHERE id = ?",
                                     (time.time(), task_id))
            await db.commit()

    async def get_progress(self) -> dict:
        """Lấy số lượng thống kê task theo trạng thái."""
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
        """Xóa toàn bộ hàng đợi."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM queue")
            await db.commit()
