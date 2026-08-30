import re

def is_youtube_ad_request(url: str, domain: str) -> bool:
    """Check if the current HTTP flow matches known YouTube ad or tracking patterns."""
    if 'youtube.com' not in domain and 'googlevideo.com' not in domain and 'youtubei' not in url and 'doubleclick.net' not in domain:
        return False

    url_lower = url.lower()

    if '/api/stats/' in url_lower:
        if 'el=adunit' in url_lower or 'adformat=' in url_lower:
            return True
        if '/atr?' in url_lower:
            return True

    if '/pcs/activeview' in url_lower:
        return True

    if '/pagead/interaction/' in url_lower or '/pagead/viewthroughconversion/' in url_lower:
        return True
        
    if 'doubleclick.net' in domain:
        return True
        
    if 'ad_' in url_lower:
        return True
        
    if 'api/stats/ads' in url_lower:
        return True

    return False

def strip_youtube_ads(body: str) -> tuple[bool, str]:
    """Strip out ad config from youtube API responses and initial HTML."""
    if not body or ('adPlacements' not in body and 'playerAds' not in body and 'adSlots' not in body):
        return False, body

    modified = False
    
    if '"adPlacements"' in body:
        body = body.replace('"adPlacements"', '"adPlacements_BLOCKED"')
        modified = True
        
    if '"playerAds"' in body:
        body = body.replace('"playerAds"', '"playerAds_BLOCKED"')
        modified = True
        
    if '"adSlots"' in body:
        body = body.replace('"adSlots"', '"adSlots_BLOCKED"')
        modified = True

    # Inject Anti-AFK script for HTML pages
    if '</body>' in body:
        anti_afk_js = """
        <script>
        setInterval(function(){
            var popups = document.querySelectorAll('yt-confirm-dialog-renderer, tp-yt-paper-dialog');
            for (var i = 0; i < popups.length; i++) {
                var text = popups[i].innerText || "";
                if (text.includes("Video đã tạm dừng") || text.includes("Video paused")) {
                    var btn = popups[i].querySelector('#confirm-button, button[aria-label="Có"], button[aria-label="Yes"]');
                    if (btn) {
                        btn.click();
                        console.log("Anti-AFK: Auto-clicked Continue Watching");
                    }
                }
            }
        }, 5000);
        </script>
        </body>
        """
        body = body.replace('</body>', anti_afk_js)
        modified = True

    return modified, body
