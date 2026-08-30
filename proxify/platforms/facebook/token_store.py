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


# ── File-based token retrieval ─────────────────────────────────────────


async def get_saved_tokens() -> Optional[dict]:
    """Load saved Facebook tokens from the data directory.

    Checks two locations in order:
    1. ``<project>/data/tokens_facebook.json`` (Docker volume mount)
    2. ``<package>/platforms/facebook/tokens.json`` (local fallback)

    Returns:
        Parsed token dict, or ``None`` if not found.
    """
    token_file = Path(__file__).parent.parent.parent.parent / "data" / "tokens_facebook.json"
    if not token_file.exists():
        token_file = Path(__file__).parent / "tokens.json"
        if not token_file.exists():
            return None
    try:
        return json.loads(token_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read FB tokens: {e}")
        return None


# ── DB-based cookie retrieval ──────────────────────────────────────────


async def get_cookies_and_ua_from_db(pool) -> tuple[dict, str]:
    """Fetch the most recent Facebook cookies and User-Agent from the request DB.

    Args:
        pool: Database connection pool (``proxify.database.pool``).

    Returns:
        Tuple of (cookies_dict, user_agent_string).
    """
    cookie_str = ""
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    try:
        with pool.cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT request_headers FROM public.requests "
                "WHERE domain LIKE '%facebook.com%' "
                "AND request_headers ILIKE '%c_user=%' "
                "AND request_headers ILIKE '%xs=%' "
                "ORDER BY timestamp_epoch DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row["request_headers"]:
                headers = json.loads(row["request_headers"])
                cookie_str = headers.get("cookie", "") or headers.get("Cookie", "")
                user_agent = (
                    headers.get("user-agent", "")
                    or headers.get("User-Agent", "")
                    or user_agent
                )
    except Exception as e:
        logger.error(f"[TokenStore] Error fetching cookies from DB: {e}")

    if not cookie_str:
        tokens = await get_saved_tokens()
        if tokens:
            cookie_str = tokens.get("cookie", "")

    return cookie_str, user_agent


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
