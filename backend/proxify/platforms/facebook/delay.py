"""
Crawl Delay Strategy
=====================
Human-like delay functions using Gaussian distribution.
Configurable via ``CrawlDelayConfig`` dataclass.

Pattern: Strategy — delay behavior is configurable via ``CrawlDelayConfig``
without changing the calling code.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlDelayConfig:
    """Configuration for human-like crawl delays.

    All values in seconds. Gaussian distribution is clamped
    to [min, max] to avoid negative or extreme delays.
    """

    # Page-level delays (between pagination requests)
    page_mean: float = 4.0
    page_std: float = 1.5
    page_min: float = 2.0
    page_max: float = 8.0

    # Comment/reply-level delays (between sub-requests)
    comment_mean: float = 0.7
    comment_std: float = 0.3
    comment_min: float = 0.3
    comment_max: float = 1.5

    # Occasional long pause simulating "user reading"
    long_pause_chance: float = 0.10
    long_pause_min: float = 5.0
    long_pause_max: float = 15.0


# ── Default configuration ──────────────────────────────────────────────

DEFAULT_DELAY_CONFIG = CrawlDelayConfig()


# ── Delay functions ────────────────────────────────────────────────────


def _gaussian_clamped(mean: float, std: float, lo: float, hi: float) -> float:
    """Sample from Gaussian, clamped to [lo, hi]."""
    return max(lo, min(hi, random.gauss(mean, std)))


def page_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float:
    """Calculate a human-like delay between page requests.

    Returns seconds to sleep. May include a "long pause" with
    ``config.long_pause_chance`` probability.
    """
    delay = _gaussian_clamped(
        config.page_mean, config.page_std, config.page_min, config.page_max,
    )
    if random.random() < config.long_pause_chance:
        delay += random.uniform(config.long_pause_min, config.long_pause_max)
    return delay


def comment_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float:
    """Calculate a human-like delay between comment/reply requests."""
    return _gaussian_clamped(
        config.comment_mean, config.comment_std, config.comment_min, config.comment_max,
    )
