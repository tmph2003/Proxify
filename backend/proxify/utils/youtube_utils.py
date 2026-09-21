import re

# Dedicated Google/YouTube ad networks and service domains.
# Requests to these domains are 100% advertisement or tracking and should always be dropped with HTTP 204.
AD_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
)

# Ad configuration and renderer keys present in YouTube watch HTML and Innertube JSON APIs.
# NOTE: Never include generic UI tokens like "masthead" here because YouTube's topbar navigation
# and search box are rendered via <ytd-masthead id="masthead" slot="masthead">.
AD_CONFIG_KEYS = (
    "adPlacements",
    "adSlots",
    "playerAds",
    "adBreakHeartbeatParams",
    "adSlotRenderer",
    "inFeedAdLayoutRenderer",
    "promotedVideoRenderer",
    "promotedSparklesWebRenderer",
    "compactPromotedVideoRenderer",
    "statementBannerRenderer",
    "primetimeMastheadRenderer",
    "adsEngagementPanelContentRenderer",
)

def is_youtube_ad_request(url: str, domain: str) -> bool:
    """Check if the current HTTP flow matches known YouTube ad or tracking patterns."""
    domain_lower = domain.lower() if domain else ""
    url_lower = url.lower() if url else ""

    # 1. Direct ad networks
    if any(ad_d in domain_lower for ad_d in AD_DOMAINS):
        return True

    # Fast exit for non-YouTube / non-Innertube domains
    if "youtube.com" not in domain_lower and "youtubei" not in url_lower:
        return False

    # 2. Never block googlevideo.com stream chunks at the request level.
    # Blocking video stream chunks breaks MediaSource MSE and causes fatal player errors.
    if "googlevideo.com" in domain_lower:
        return False

    # 3. Google/YouTube PageAd endpoints
    if "/pagead/" in url_lower:
        return True

    # 4. YouTube ad telemetry and metrics
    if "/api/stats/ads" in url_lower:
        return True

    if "/pcs/activeview" in url_lower:
        return True

    if "/ptracking" in url_lower:
        return True

    if "/youtubei/v1/player/ad_break" in url_lower or "/youtubei/v1/att/" in url_lower:
        return True

    if "/api/stats/" in url_lower:
        # Block ad-specific metric calls, but preserve regular detailpage heartbeat
        if "el=adunit" in url_lower or "adformat=" in url_lower:
            return True
        if "/atr?" in url_lower and "el=adunit" in url_lower:
            return True

    # 5. Ad query parameter patterns (e.g. ad_cpn, ad_format, ad_v)
    if bool(re.search(r"[?&]ad_(?:cpn|format|v)=", url_lower)):
        return True

    return False

def strip_youtube_ads(body: str) -> tuple[bool, str]:
    """Strip out ad config and renderers from YouTube watch HTML and Innertube API responses."""
    if not body:
        return False, body

    if not any(k in body for k in AD_CONFIG_KEYS):
        return False, body

    modified = False
    for key in AD_CONFIG_KEYS:
        target = f'"{key}"'
        if target in body:
            body = body.replace(target, f'"{key}_BLOCKED"')
            modified = True

    return modified, body

