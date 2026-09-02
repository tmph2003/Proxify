"""Shared content-type utilities and constants used across Proxify modules."""

# Max response body size to store (5 MB)
MAX_RESPONSE_SIZE = 5 * 1024 * 1024

# Text-based content types — tuple for efficient startswith() check
_TEXT_CONTENT_PREFIXES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "application/xml",
    "application/xhtml+xml",
    "application/x-www-form-urlencoded",
    "application/graphql",
    "application/ld+json",
    "application/manifest+json",
    "application/vnd.api+json",
    "image/svg+xml",
)


def is_text_content(content_type: str) -> bool:
    """Check if a content type is text-based.

    Uses startswith() with a tuple of known text content-type prefixes
    for both correctness and performance.
    """
    if not content_type:
        return False
    ct = content_type.lower().split(";")[0].strip()
    return ct.startswith(_TEXT_CONTENT_PREFIXES)
