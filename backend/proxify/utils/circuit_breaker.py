"""
Crawl Circuit Breaker
======================
Global circuit breaker that stops ALL crawling when a soft-block is detected.
Prevents Facebook from escalating a temporary checkpoint into a permanent ban.

States:
    CLOSED  → Normal operation, requests flow through
    OPEN    → Soft-block detected, all requests blocked, cooldown active
    HALF_OPEN → Cooldown expired, allow 1 test request to check if block lifted

Usage:
    from proxify.utils.circuit_breaker import crawl_breaker

    if not crawl_breaker.allow_request():
        # Don't send request — still in cooldown
        return

    # ... send request ...

    if is_blocked:
        crawl_breaker.trip("checkpoint detected")
"""

import logging
import random
import time
import threading

logger = logging.getLogger("proxify.circuit_breaker")

# Cooldown range in seconds (30-60 minutes)
MIN_COOLDOWN = 30 * 60  # 30 minutes
MAX_COOLDOWN = 60 * 60  # 60 minutes


class CrawlCircuitBreaker:
    """Thread-safe circuit breaker for crawl operations.
    
    When tripped (soft-block detected), blocks all crawl requests
    for a random cooldown period (30-60 minutes) to avoid
    escalating a temporary block into a permanent ban.
    """

    # States
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        min_cooldown: int = MIN_COOLDOWN,
        max_cooldown: int = MAX_COOLDOWN,
    ):
        self._state = self.CLOSED
        self._lock = threading.Lock()
        self._trip_time: float = 0
        self._cooldown_seconds: float = 0
        self._trip_reason: str = ""
        self._trip_count: int = 0
        self._min_cooldown = min_cooldown
        self._max_cooldown = max_cooldown

    @property
    def state(self) -> str:
        """Current state, auto-transitioning OPEN→HALF_OPEN when cooldown expires."""
        with self._lock:
            if self._state == self.OPEN:
                elapsed = time.time() - self._trip_time
                if elapsed >= self._cooldown_seconds:
                    self._state = self.HALF_OPEN
                    logger.info(
                        f"⚡ Circuit breaker → HALF_OPEN "
                        f"(cooldown {self._cooldown_seconds:.0f}s expired)"
                    )
            return self._state

    @property
    def remaining_cooldown(self) -> float:
        """Seconds remaining in cooldown. 0 if not in OPEN state."""
        with self._lock:
            if self._state != self.OPEN:
                return 0
            remaining = self._cooldown_seconds - (time.time() - self._trip_time)
            return max(0, remaining)

    def allow_request(self) -> bool:
        """Check if a crawl request is allowed.
        
        Returns True if the request can proceed (CLOSED or HALF_OPEN).
        Returns False if still in cooldown (OPEN).
        """
        current = self.state  # triggers auto-transition
        if current == self.CLOSED:
            return True
        if current == self.HALF_OPEN:
            # Allow exactly 1 test request
            return True
        # OPEN — blocked
        return False

    def trip(self, reason: str = "") -> None:
        """Trip the circuit breaker (block detected).
        
        Sets state to OPEN with a random cooldown between
        min_cooldown and max_cooldown seconds.
        """
        with self._lock:
            self._state = self.OPEN
            self._trip_time = time.time()
            self._cooldown_seconds = random.uniform(
                self._min_cooldown, self._max_cooldown
            )
            self._trip_reason = reason
            self._trip_count += 1

        cooldown_min = self._cooldown_seconds / 60
        logger.warning(
            f"🛑 Circuit breaker TRIPPED! Reason: {reason}. "
            f"All crawling blocked for {cooldown_min:.0f} minutes. "
            f"(trip #{self._trip_count})"
        )

    def record_success(self) -> None:
        """Record a successful request (used after HALF_OPEN test).
        
        Transitions HALF_OPEN → CLOSED.
        """
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._state = self.CLOSED
                logger.info(
                    "✅ Circuit breaker → CLOSED (test request succeeded)"
                )

    def reset(self) -> None:
        """Force reset to CLOSED state (manual override)."""
        with self._lock:
            self._state = self.CLOSED
            self._trip_time = 0
            self._cooldown_seconds = 0
            self._trip_reason = ""
        logger.info("🔄 Circuit breaker manually reset to CLOSED")

    @property
    def info(self) -> dict:
        """Return circuit breaker status for UI/logging."""
        return {
            "state": self.state,
            "trip_count": self._trip_count,
            "trip_reason": self._trip_reason,
            "remaining_cooldown_seconds": round(self.remaining_cooldown),
            "remaining_cooldown_minutes": round(self.remaining_cooldown / 60, 1),
        }

    def __repr__(self) -> str:
        return (
            f"<CrawlCircuitBreaker state={self.state} "
            f"trips={self._trip_count} "
            f"cooldown={self.remaining_cooldown:.0f}s>"
        )


# ─── Global singleton ──────────────────────────────────────────────────────
crawl_breaker = CrawlCircuitBreaker()
"""Global circuit breaker instance shared by all crawler operations."""
