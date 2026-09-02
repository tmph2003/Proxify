"""
Facebook Session State Manager
================================
Manages dynamic form parameters (__req, __s, __spin_t) to simulate
a real browser session during crawling.

Facebook detects bots by checking that these parameters change between
requests. Sending static values from the template is the #1 detection signal.

Pattern: Encapsulates session state mutation into a single responsibility class.
"""

import random
import string
import time
from typing import Optional


class SessionStateManager:
    """Manages dynamic Facebook form parameters to mimic a real browser session.

    Facebook tracks:
        - ``__req``: Base36-encoded request counter (must increment)
        - ``__s``: Random session token (must change each request)
        - ``__spin_t``: Unix timestamp (must be current, not stale)

    Usage::

        state = SessionStateManager()
        for i in range(100):
            data = template_form_data.copy()
            state.update_params(data)  # mutates data in place
    """

    _ALPHABET = string.digits + string.ascii_lowercase

    def __init__(self, counter_offset: Optional[int] = None) -> None:
        """Initialize with a random counter offset.

        Args:
            counter_offset: Starting value for __req counter.
                If None, a random offset (5–15) is chosen to simulate
                a browser that already made some requests.
        """
        self._counter_offset = counter_offset if counter_offset is not None else random.randint(5, 15)
        self._request_count = 0

    # ── Public API ─────────────────────────────────────────────────────

    def update_params(self, data: dict) -> None:
        """Update ``__req``, ``__s``, and ``__spin_t`` in *data* (in-place).

        Call this once per request before sending the form data.
        """
        counter = self._counter_offset + self._request_count
        data["__req"] = self._encode_base36(counter)
        data["__s"] = self._gen_session_token()
        data["__spin_t"] = str(int(time.time()))
        self._request_count += 1

    @property
    def request_count(self) -> int:
        """Number of requests processed so far."""
        return self._request_count

    def reset(self) -> None:
        """Reset counter (e.g. when starting a new crawl session)."""
        self._counter_offset = random.randint(5, 15)
        self._request_count = 0

    # ── Internal Helpers ───────────────────────────────────────────────

    @classmethod
    def _encode_base36(cls, n: int) -> str:
        """Encode *n* as a base-36 string (digits + lowercase a–z).

        Facebook's ``__req`` uses this encoding:
        ``0, 1, ..., 9, a, b, ..., z, 10, 11, ...``
        """
        if n == 0:
            return "0"
        chars = cls._ALPHABET
        parts: list[str] = []
        while n > 0:
            parts.append(chars[n % 36])
            n //= 36
        return "".join(reversed(parts))

    @staticmethod
    def _gen_session_token() -> str:
        """Generate a random ``__s`` token matching Facebook's format.

        Format: three colon-separated 6-char alphanumeric tokens,
        e.g. ``'k56usl:6nkt26:ojx4x3'``
        """
        pool = string.ascii_lowercase + string.digits

        def _part() -> str:
            return "".join(random.choices(pool, k=6))

        return f"{_part()}:{_part()}:{_part()}"
