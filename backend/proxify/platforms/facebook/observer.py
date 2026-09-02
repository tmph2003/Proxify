class CrawlerStateObserver:
    """Observer Pattern: Manages state updates and emits them without tightly coupling to the crawler logic.
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
