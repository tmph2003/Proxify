import asyncio
import uuid
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("proxify.facebook.bridge")

class ExtensionBridge:
    """Manages jobs for the Chrome Extension to execute natively."""
    
    def __init__(self):
        self.pending_jobs: Dict[str, dict] = {}
        self.results: Dict[str, Any] = {}
        self.events: Dict[str, asyncio.Event] = {}

    def has_jobs(self) -> bool:
        return len(self.pending_jobs) > 0

    def get_job(self) -> Optional[dict]:
        """Get the oldest pending job."""
        if not self.pending_jobs:
            return None
        # Pop the first job
        job_id = next(iter(self.pending_jobs))
        return self.pending_jobs.pop(job_id)

    async def execute_request(self, url: str, method: str = "POST", headers: dict = None, data: str = None, timeout: int = 30) -> dict:
        """Push a job to the extension and wait for the result."""
        job_id = str(uuid.uuid4())
        
        # Clean up headers, only send what's strictly necessary if we are running in browser.
        # Actually, if we run in browser, we don't need cookie or user-agent because browser sends it automatically!
        # But we MUST send content-type and X-ASBD-ID etc if required for GraphQL.
        safe_headers = {}
        if headers:
            for k, v in headers.items():
                k_lower = k.lower()
                # Skip forbidden headers in Fetch API
                if k_lower in ["cookie", "user-agent", "host", "referer", "origin", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "accept-encoding", "connection"]:
                    continue
                safe_headers[k] = v

        job = {
            "id": job_id,
            "url": url,
            "method": method,
            "headers": safe_headers,
            "body": data
        }
        
        self.pending_jobs[job_id] = job
        self.events[job_id] = asyncio.Event()
        
        logger.info(f"[Bridge] Dispatched job {job_id} to Extension")
        
        try:
            # Wait for result with timeout
            await asyncio.wait_for(self.events[job_id].wait(), timeout=timeout)
            result = self.results.pop(job_id, None)
            return result or {"status": "error", "message": "No result data"}
        except asyncio.TimeoutError:
            logger.error(f"[Bridge] Job {job_id} timed out after {timeout}s")
            self.pending_jobs.pop(job_id, None)
            self.results.pop(job_id, None)
            self.events.pop(job_id, None)
            return {"status": "error", "message": "Extension fetch timed out. Is the browser open?"}

    def complete_job(self, job_id: str, data: dict):
        """Called by the API endpoint when extension submits a result."""
        if job_id in self.events:
            self.results[job_id] = data
            self.events[job_id].set()
            # Clean up event later
            self.events.pop(job_id, None)
            logger.info(f"[Bridge] Job {job_id} completed by Extension")
        else:
            logger.warning(f"[Bridge] Received result for unknown/expired job {job_id}")

# Global singleton
bridge = ExtensionBridge()
