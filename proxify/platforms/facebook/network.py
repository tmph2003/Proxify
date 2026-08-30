import asyncio
import time
from typing import Optional
from proxify.utils.stealth import StealthSessionManager

class GlobalNetworkClient:
    """Borg pattern: All instances share the same state.
    Ensures that only ONE network request to Facebook can happen at a time across the entire app.
    """
    _shared_state = {}

    def __init__(self, manager: Optional[StealthSessionManager] = None):
        self.__dict__ = self._shared_state
        if not hasattr(self, 'initialized'):
            self.manager = manager or StealthSessionManager(
                max_retries=2, base_delay=3.0, timeout=15.0,
            )
            self._rate_limit_lock = asyncio.Lock()
            self._last_request_time = 0.0
            self.initialized = True
        elif manager is not None:
            # Update manager if explicitly provided again
            self.manager = manager

    async def safe_request(self, *args, **kwargs):
        """Wrapper around manager.request that enforces a global rate limit and Mutex lock.
        No two network requests to Facebook can overlap.
        """
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            # Enforce at least 2.5 seconds between ANY two requests globally
            if elapsed < 2.5:
                await asyncio.sleep(2.5 - elapsed)
            
            try:
                return await self.manager.request(*args, **kwargs)
            finally:
                self._last_request_time = time.time()
