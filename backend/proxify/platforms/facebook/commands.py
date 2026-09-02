from abc import ABC, abstractmethod
import logging

logger = logging.getLogger("proxify.facebook.commands")

class BaseCommand(ABC):
    """Command Pattern: Encapsulates a request as an object."""
    @abstractmethod
    async def execute(self):
        pass

class RefreshCommand(BaseCommand):
    def __init__(self, receiver, urls: list[str], template: dict = None, client_cookie: str = None):
        self.receiver = receiver
        self.urls = urls
        self.template = template
        self.client_cookie = client_cookie

    async def execute(self):
        logger.info(f"[Command] Executing RefreshCommand for {len(self.urls)} posts")
        await self.receiver._execute_crawl_specific_posts(self.urls, self.template, self.client_cookie)


class CrawlFeedCommand(BaseCommand):
    def __init__(self, receiver, group_id: str, start_ts: int, end_ts: int, template: dict = None, client_cookie: str = None, reset_cursor: bool = True):
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
    def __init__(self, receiver, post_id: str, feedback_id: str, template: dict = None, client_cookie: str = None):
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

