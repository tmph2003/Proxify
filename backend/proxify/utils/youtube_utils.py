import re

# Dedicated Google/YouTube ad networks and service domains.
# Requests to these domains are 100% advertisement or tracking and should always be dropped with HTTP 204.
AD_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
)

# Root-level Ad container keys in YouTube watch HTML and Innertube JSON APIs.
# ARCHITECTURAL NOTE:
# NEVER include internal layout/renderer tokens (e.g., "instreamVideoAdRenderer", "slotExpirationTriggers",
# "skipAdViewModel") here! Mutating internal tokens creates malformed data structures.
# When YouTube's player encounters layouts with missing triggers/viewmodels, the ad state machine crashes,
# the ad slot never expires, an invisible overlay stays permanently mounted over the <video> element,
# and getPresentingPlayerType() remains locked in AD mode (2) which disables Spacebar/'k' and absorbs all clicks.
#
# Pruning ONLY root ad containers (adPlacements, adSlots, playerAds, adBreakHeartbeatParams) tells the player
# that the video has zero ads (identical to YouTube Premium), bypassing the ad engine cleanly while preserving
# player controls and pause/play functionality.
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

# Keys associated with YouTube's inactivity / AFK idle confirmation ("Video paused. Continue watching?")
AFK_CONFIG_KEYS = (
    "youThereRenderer",
    "lactThresholdMs",
    "you_there",
)

ALL_MUTATION_KEYS = AD_CONFIG_KEYS + AFK_CONFIG_KEYS


def is_youtube_ad_request(url: str, domain: str) -> bool:
    """Check if the current HTTP flow matches known YouTube ad or tracking patterns."""
    domain_lower = domain.lower() if domain else ""
    url_lower = url.lower() if url else ""
    clean_domain = domain_lower.split(":", 1)[0].strip()

    # 1. Direct ad networks
    if any(clean_domain == ad_d or clean_domain.endswith('.' + ad_d) for ad_d in AD_DOMAINS):
        return True

    # Fast exit for non-YouTube / non-Innertube domains
    is_yt = clean_domain == "youtube.com" or clean_domain.endswith(".youtube.com")
    if not is_yt and "youtubei" not in url_lower:
        return False

    # 2. Never block googlevideo.com or c.youtube.com stream chunks at the request level.
    # Blocking video stream chunks breaks MediaSource MSE and causes fatal player errors.
    if any(clean_domain == d or clean_domain.endswith('.' + d) for d in ("googlevideo.com", "c.youtube.com")):
        return False

    # 3. Google/YouTube PageAd endpoints
    if "/pagead/" in url_lower:
        return True

    # 4. YouTube ad telemetry and metrics
    if "/api/stats/ads" in url_lower:
        return True

    if "/pcs/activeview" in url_lower:
        return True

    if (
        "/youtubei/v1/player/ad_break" in url_lower
        or "/youtubei/v1/att/" in url_lower
        or "/youtubei/v1/get_midroll_info" in url_lower
        or "/get_midroll_info" in url_lower
    ):
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

def clean_youtube_json_data(obj) -> bool:
    """Clean ad containers and neutralize AFK idle timers from parsed YouTube Innertube JSON data in-place."""
    modified = False

    if isinstance(obj, dict):
        # 1. Neutralize youThereRenderer (inactivity prompt configuration)
        if "youThereRenderer" in obj and isinstance(obj["youThereRenderer"], dict):
            ytr = obj["youThereRenderer"]
            ytr["lactThresholdMs"] = "86400000000"  # 1000 days
            ytr["playbackPauseDelayMs"] = "86400000000"
            ytr["promptDelaySec"] = 86400000
            modified = True

        # 2. Clean playerResponse if nested
        if "playerResponse" in obj and isinstance(obj["playerResponse"], dict):
            pr = obj["playerResponse"]
            for key in ("adPlacements", "adSlots", "playerAds", "adBreakHeartbeatParams"):
                if key in pr:
                    del pr[key]
                    modified = True
            if "messages" in pr and isinstance(pr["messages"], list):
                for m in pr["messages"]:
                    if isinstance(m, dict) and "youThereRenderer" in m and isinstance(m["youThereRenderer"], dict):
                        ytr = m["youThereRenderer"]
                        ytr["lactThresholdMs"] = "86400000000"
                        ytr["playbackPauseDelayMs"] = "86400000000"
                        ytr["promptDelaySec"] = 86400000
                        modified = True

        # 3. Clean root playerResponse keys if this dict is playerResponse
        for key in ("adPlacements", "adSlots", "playerAds", "adBreakHeartbeatParams"):
            if key in obj:
                del obj[key]
                modified = True
        if "messages" in obj and isinstance(obj["messages"], list):
            for m in obj["messages"]:
                if isinstance(m, dict) and "youThereRenderer" in m and isinstance(m["youThereRenderer"], dict):
                    ytr = m["youThereRenderer"]
                    ytr["lactThresholdMs"] = "86400000000"
                    ytr["playbackPauseDelayMs"] = "86400000000"
                    ytr["promptDelaySec"] = 86400000
                    modified = True

        # 4. Clean watchNext engagement panels (specifically ads panel)
        if "watchNextResponse" in obj and isinstance(obj["watchNextResponse"], dict):
            wnr = obj["watchNextResponse"]
            if "engagementPanels" in wnr and isinstance(wnr["engagementPanels"], list):
                original_len = len(wnr["engagementPanels"])
                wnr["engagementPanels"] = [
                    p
                    for p in wnr["engagementPanels"]
                    if not (
                        isinstance(p, dict)
                        and p.get("engagementPanelSectionListRenderer", {}).get("targetId")
                        == "engagement-panel-ads"
                    )
                ]
                if len(wnr["engagementPanels"]) != original_len:
                    modified = True

        # 4. Clean feed ads from lists/sub-objects recursively
        for k, v in list(obj.items()):
            if isinstance(v, (dict, list)):
                if clean_youtube_json_data(v):
                    modified = True

    elif isinstance(obj, list):
        filtered = []
        for item in obj:
            if isinstance(item, dict):
                content = item.get("richItemRenderer", {}).get("content", {})
                if any(
                    ad_key in content
                    for ad_key in ("adSlotRenderer", "inFeedAdLayoutRenderer")
                ):
                    modified = True
                    continue
                if any(
                    ad_key in item
                    for ad_key in (
                        "adSlotRenderer",
                        "inFeedAdLayoutRenderer",
                        "promotedVideoRenderer",
                        "promotedSparklesWebRenderer",
                        "compactPromotedVideoRenderer",
                        "statementBannerRenderer",
                        "primetimeMastheadRenderer",
                    )
                ):
                    modified = True
                    continue
            if clean_youtube_json_data(item):
                modified = True
            filtered.append(item)
        if len(filtered) != len(obj):
            obj.clear()
            obj.extend(filtered)
            modified = True

    return modified

def strip_youtube_ads(body: str) -> tuple[bool, str]:
    """Strip out ad config and renderers from YouTube watch HTML and Innertube API responses.
    
    Preserves all player state machines, controls, and event listeners.
    """
    if not body:
        return False, body

    trimmed = body.strip()
    # 1. Fast path for Innertube JSON API responses (player, get_watch, browse, etc.)
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
        # Fast exit if no ad or AFK tokens exist in payload
        if not any(k in body for k in ALL_MUTATION_KEYS):
            return False, body
        try:
            import json
            data = json.loads(trimmed)
            if clean_youtube_json_data(data):
                return True, json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            return False, body
        except Exception:
            pass

    # 2. HTML Watch / Home pages
    if not any(k in body for k in ALL_MUTATION_KEYS):
        return False, body

    modified = False

    # Targeted inline player response pruning in HTML
    def prune_inline_player_response(match):
        nonlocal modified
        prefix = match.group(1)
        raw_json = match.group(2)
        suffix = match.group(3)
        try:
            import json
            pr_data = json.loads(raw_json)
            if clean_youtube_json_data(pr_data):
                modified = True
                return prefix + json.dumps(pr_data, separators=(",", ":"), ensure_ascii=False) + suffix
        except Exception:
            pass
        return match.group(0)

    new_body = re.sub(
        r'(var\s+ytInitialPlayerResponse\s*=\s*)(\{.*?\})(\s*;\s*(?:var\s+ytInitialData|</script>))',
        prune_inline_player_response,
        body,
        flags=re.DOTALL,
    )

    # For any remaining high-level ad containers, safely rename ONLY container keys.
    # NEVER rename internal tokens, and NEVER mutate webResponseContextPreloadData.
    for key in ("adPlacements", "adSlots", "playerAds", "adBreakHeartbeatParams"):
        target = f'"{key}"'
        if target in new_body:
            new_body = new_body.replace(target, f'"{key}_BLOCKED"')
            modified = True

    # Neutralize any raw lactThresholdMs occurrences in body to 1000 days (86400000000 ms)
    if "lactThresholdMs" in new_body:
        new_body, count = re.subn(
            r'("lactThresholdMs"\s*:\s*"?)\d+("?)',
            r'\g<1>86400000000\g<2>',
            new_body,
        )
        if count > 0:
            modified = True

    return modified, new_body


YOUTUBE_WATCHDOG_SCRIPT = (
    """(function(){if(window.__proxify_anti_afk__)return;window.__proxify_anti_afk__=true;"""
    """var TAG="[Proxify Anti-AFK]";"""
    """function keepLactFresh(){try{window._lact=Date.now();}catch(e){}}"""
    """setInterval(keepLactFresh,15000);keepLactFresh();"""
    """["pointerdown","mousedown","keydown","touchstart"].forEach(function(e){"""
    """window.addEventListener(e,keepLactFresh,{capture:true,passive:true});});"""
    """function clickBtn(root){if(!root)return false;"""
    """var sels=["#confirm-button button","#confirm-button .yt-spec-button-shape-next","yt-button-shape button","#confirm-button a","#confirm-button",".yt-confirm-dialog-renderer #confirm-button"];"""
    """for(var i=0;i<sels.length;i++){var b=root.querySelector(sels[i]);if(b){"""
    """if(b.shadowRoot){var inner=b.shadowRoot.querySelector("button");if(inner){inner.click();return true;}}"""
    """var nb=b.querySelector("button")||b;nb.click();return true;}}"""
    """var btns=root.querySelectorAll("button, a, tp-yt-paper-button");"""
    """for(var j=0;j<btns.length;j++){var el=btns[j];var t=(el.textContent||"").trim().toLowerCase();var a=(el.getAttribute("aria-label")||"").trim().toLowerCase();"""
    """if(t==="có"||t==="yes"||t==="ok"||t.indexOf("tiếp tục")!==-1||t.indexOf("continue")!==-1||a==="có"||a==="yes"||a.indexOf("continue")!==-1){"""
    """el.click();return true;}}return false;}"""
    """function resumeVideo(){try{var v=document.querySelector("video.html5-main-video")||document.querySelector("video");"""
    """if(v&&v.paused&&v.readyState>=2){var p=v.play();if(p&&p.catch){p.catch(function(){"""
    """var mp=document.getElementById("movie_player");if(mp&&typeof mp.playVideo==="function"){mp.playVideo();}});}}}catch(e){}}"""
    """function checkAndDismiss(){var dlgs=document.querySelectorAll("yt-confirm-dialog-renderer, tp-yt-paper-dialog, ytmusic-you-there-renderer, ytd-modal-with-title-and-button-renderer");"""
    """for(var i=0;i<dlgs.length;i++){var d=dlgs[i];var s=window.getComputedStyle(d);"""
    """var hidden=d.hidden||d.getAttribute("aria-hidden")==="true"||s.display==="none"||s.visibility==="hidden";"""
    """var t=(d.textContent||"").toLowerCase();"""
    """var isAfk=t.indexOf("tạm dừng")!==-1||t.indexOf("tiếp tục xem")!==-1||t.indexOf("paused")!==-1||t.indexOf("continue watching")!==-1||t.indexOf("still watching")!==-1||d.tagName.toLowerCase()==="ytmusic-you-there-renderer";"""
    """if(!hidden&&isAfk){if(clickBtn(d)){setTimeout(resumeVideo,300);return true;}}}"""
    """var pd=document.querySelector("tp-yt-paper-dialog[opened]");"""
    """if(pd){var pt=(pd.textContent||"").toLowerCase();"""
    """if(pt.indexOf("tạm dừng")!==-1||pt.indexOf("paused")!==-1||pt.indexOf("tiếp tục")!==-1||pt.indexOf("continue")!==-1){"""
    """if(clickBtn(pd)){setTimeout(resumeVideo,300);return true;}}}return false;}"""
    """setInterval(checkAndDismiss,500);document.addEventListener("yt-popup-opened",checkAndDismiss);"""
    """document.addEventListener("yt-action",checkAndDismiss);console.log(TAG,"Watchdog active");})();"""
)


def inject_youtube_anti_afk(html: str, nonce: str = "") -> str:
    """Inject inline anti-AFK watchdog script into YouTube watch HTML."""
    if not html or "__proxify_anti_afk__" in html:
        return html

    if not nonce:
        # Extract nonce from existing script tag in the HTML if available
        m = re.search(r'<script\s+nonce="([^"]+)"', html)
        if m:
            nonce = m.group(1)

    nonce_attr = f' nonce="{nonce}"' if nonce else ""
    script_tag = f'<script{nonce_attr}>{YOUTUBE_WATCHDOG_SCRIPT}</script>'

    if "</body>" in html:
        return html.replace("</body>", f"{script_tag}</body>", 1)
    elif "</head>" in html:
        return html.replace("</head>", f"{script_tag}</head>", 1)
    return html + script_tag


