import asyncio
import time
import uuid
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("proxify.facebook.bridge")

class ExtensionBridge:
    """Manages jobs for Chrome Extensions to execute natively, with Multi-Tenant Isolation.
    
    Each client/tenant has an isolated job queue so Client A never receives Client B's jobs.
    """
    
    def __init__(self):
        # Mapping: client_id -> Dict[job_id, job]
        self.client_queues: Dict[str, Dict[str, dict]] = {}
        # Mapping: job_id -> client_id (for fast lookup on result submission)
        self.job_to_client: Dict[str, str] = {}
        # Results and events
        self.results: Dict[str, Any] = {}
        self.events: Dict[str, asyncio.Event] = {}
        # Mapping: client_id -> float (timestamp of last poll)
        self.client_last_poll: Dict[str, float] = {}

    def is_connected(self, client_id: str = "default", threshold: float = 60.0) -> bool:
        """Check if the Chrome extension for a specific client_id has polled recently."""
        last_poll = self.client_last_poll.get(client_id, 0.0)
        return (time.time() - last_poll) < threshold

    def has_jobs(self, client_id: str = "default") -> bool:
        """Check if there are pending jobs for a specific client_id."""
        queue = self.client_queues.get(client_id)
        return bool(queue and len(queue) > 0)

    def get_job(self, client_id: str = "default") -> Optional[dict]:
        """Get the oldest pending job for a specific client_id and update heartbeat."""
        self.client_last_poll[client_id] = time.time()
        queue = self.client_queues.get(client_id)
        if not queue:
            return None
        # Pop the first job in FIFO order
        job_id = next(iter(queue))
        return queue.pop(job_id)

    async def execute_request(
        self,
        url: str,
        method: str = "POST",
        headers: dict = None,
        data: str = None,
        timeout: int = 30,
        client_id: str = "default"
    ) -> dict:
        """Push a job to the specific client's extension queue and wait for the result."""
        # GUARDRAIL: Browser Bridge is strictly reserved for /api/graphql/ requests.
        # Calling window.fetch() on HTML permalinks or non-GraphQL URLs inside the Facebook tab
        # triggers Sec-Fetch-Dest: empty on HTML pages, which Meta Edge detects as in-tab scraping
        # and immediately flags the user account with a checkpoint!
        if "/api/graphql" not in url:
            logger.error(
                f"[Bridge] REJECTED unsafe non-GraphQL request to '{url}'. "
                f"Browser Bridge strictly permits /api/graphql/ endpoints to prevent account checkpoints."
            )
            return {
                "status": "error",
                "status_code": 403,
                "error": "Unsafe in-tab request blocked: Only /api/graphql/ endpoints are permitted via Extension Bridge.",
                "text": ""
            }

        job_id = str(uuid.uuid4())
        
        # Clean up headers, only send what's strictly necessary if we are running in browser.
        # Browser handles cookie, user-agent, host, origin, sec-ch-* automatically.
        safe_headers = {}
        target_group_url = ""
        if headers:
            for k, v in headers.items():
                k_lower = k.lower()
                if k_lower == "referer" and "/groups/" in v:
                    target_group_url = v
                # Skip forbidden headers in Fetch API
                if k_lower in ["cookie", "user-agent", "host", "referer", "origin", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "accept-encoding", "connection"]:
                    continue
                safe_headers[k] = v

        if method.upper() == "POST":
            safe_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        job = {
            "id": job_id,
            "url": url,
            "method": method,
            "headers": safe_headers,
            "body": data,
            "target_group_url": target_group_url,
            "client_id": client_id
        }
        
        if client_id not in self.client_queues:
            self.client_queues[client_id] = {}
        self.client_queues[client_id][job_id] = job
        self.job_to_client[job_id] = client_id
        self.events[job_id] = asyncio.Event()
        
        logger.debug(f"[Bridge] Dispatched job {job_id} to Extension (client_id={client_id})")
        
        try:
            # Wait for result with timeout
            await asyncio.wait_for(self.events[job_id].wait(), timeout=timeout)
            result = self.results.pop(job_id, None)
            return result or {"status": "error", "message": "No result data"}
        except asyncio.TimeoutError:
            logger.error(f"[Bridge] Job {job_id} for client '{client_id}' timed out after {timeout}s")
            if client_id in self.client_queues:
                self.client_queues[client_id].pop(job_id, None)
            self.job_to_client.pop(job_id, None)
            self.results.pop(job_id, None)
            self.events.pop(job_id, None)
            return {"status": "error", "message": f"Extension fetch timed out for client '{client_id}'. Is Chrome open with the Facebook tab?"}

    def complete_job(self, job_id: str, data: dict, client_id: Optional[str] = None):
        """Called by the API endpoint when extension submits a result."""
        # Cleanup queue reference if still present
        cid = client_id or self.job_to_client.get(job_id)
        if cid and cid in self.client_queues:
            self.client_queues[cid].pop(job_id, None)
        self.job_to_client.pop(job_id, None)

        if job_id in self.events:
            self.results[job_id] = data
            self.events[job_id].set()
            self.events.pop(job_id, None)
            in_tab = data.get("executed_in_tab", False)
            tab_url = data.get("tab_url", "N/A")
            tab_id = data.get("tab_id", "N/A")
            err_detail = data.get("tab_error", "")
            logger.debug(f"[Bridge] Job {job_id} (client={cid}) completed: in_tab={in_tab}, tab_id={tab_id}, tab_url={tab_url}, err={err_detail}")
        else:
            logger.warning(f"[Bridge] Received result for unknown/expired job {job_id}")

    # Backward compatibility properties for legacy code/tests
    @property
    def last_poll_time(self) -> float:
        return self.client_last_poll.get("default", 0.0)

    @last_poll_time.setter
    def last_poll_time(self, val: float):
        self.client_last_poll["default"] = val

    @property
    def pending_jobs(self) -> dict:
        return self.client_queues.get("default", {})

# Global singleton
bridge = ExtensionBridge()
