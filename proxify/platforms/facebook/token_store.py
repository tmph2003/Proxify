"""
Facebook Token Store
=====================
Handles retrieval of authentication tokens, cookies, and templates
from various sources (file, database, user input).

Single Responsibility: this module only deals with loading/parsing
credential data — no crawling logic.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("proxify.facebook.token_store")


# ── In-Memory Token Store ──────────────────────────────────────────────
IN_MEMORY_TEMPLATES = {}

async def get_saved_tokens() -> Optional[dict]:
    """Retrieve templates from memory."""
    if IN_MEMORY_TEMPLATES:
        return IN_MEMORY_TEMPLATES
    return None


# ── Cookie string parsing ─────────────────────────────────────────────


def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Parse a raw cookie string into a dict.

    Handles both semicolon-separated (standard) and comma-separated formats.
    """
    if not cookie_str:
        return {}

    separator = "," if "," in cookie_str and ";" not in cookie_str else ";"
    cookies: dict[str, str] = {}
    for pair in cookie_str.split(separator):
        if "=" in pair:
            k, v = pair.strip().split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


# ── Template parsing helpers ───────────────────────────────────────────


def extract_templates(tokens: dict) -> tuple[Optional[dict], Optional[dict], Optional[dict]]:
    """Extract feed, comment, and reply templates from a tokens dict.

    Handles both flat format (single template) and nested format
    (separate feed/comment/reply templates).

    The nested format is preferred because it also includes comment/reply
    templates when available. The template_fetcher saves BOTH formats for
    backward compatibility, so we must check 'feed' key FIRST.

    Returns:
        Tuple of (feed_template, comment_template, reply_template).
    """
    # Nested format: has a 'feed' sub-dict with its own 'form_data'
    feed = tokens.get("feed")
    if isinstance(feed, dict) and "form_data" in feed:
        return (
            feed,
            tokens.get("comment"),
            tokens.get("reply"),
        )

    # Flat format: entire dict is the feed template (legacy)
    if "form_data" in tokens:
        return tokens, None, None

    return None, None, None
