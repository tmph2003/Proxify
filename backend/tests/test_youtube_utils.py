import pytest
from proxify.utils.youtube_utils import is_youtube_ad_request, strip_youtube_ads

def test_is_youtube_ad_request():
    # 1. Direct ad networks
    assert is_youtube_ad_request("https://googleads.g.doubleclick.net/pagead/interaction/", "googleads.g.doubleclick.net")
    assert is_youtube_ad_request("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js", "pagead2.googlesyndication.com")
    assert is_youtube_ad_request("https://www.googleadservices.com/pagead/conversion/", "www.googleadservices.com")
    assert is_youtube_ad_request("https://adservice.google.com/adsid/google/ui", "adservice.google.com")

    # 2. YouTube specific ad endpoints
    assert is_youtube_ad_request("https://youtube.com/pagead/parallel?video_id=123", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/api/stats/ads?v=123", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/api/stats/atr?adformat=1", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/pcs/activeview", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/ptracking?docid=123", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/youtubei/v1/player/ad_break", "youtube.com")

    # 3. Legitimate video playback (MUST NOT be blocked)
    assert not is_youtube_ad_request("https://youtube.com/watch?v=123", "youtube.com")
    assert not is_youtube_ad_request("https://youtube.com/shorts/abc", "youtube.com")
    assert not is_youtube_ad_request("https://youtubei.googleapis.com/youtubei/v1/next", "youtubei.googleapis.com")
    assert not is_youtube_ad_request("https://s.youtube.com/api/stats/playback?docid=123", "s.youtube.com")
    assert not is_youtube_ad_request("https://s.youtube.com/api/stats/atr?ns=yt&el=detailpage", "s.youtube.com")
    
    # 4. googlevideo.com video stream chunks must never be blocked at URL level
    assert not is_youtube_ad_request("https://rr1---sn-abc.googlevideo.com/videoplayback?expire=123", "rr1---sn-abc.googlevideo.com")
    assert not is_youtube_ad_request("https://example.com/api/stats", "example.com")

def test_strip_youtube_ads():
    # No ads case
    html_clean = "<html><body>Clean page</body></html>"
    modified, new_html = strip_youtube_ads(html_clean)
    assert modified is False
    assert new_html == html_clean

    # Ads case: all modern keys must be pruned
    payload_ads = (
        '{"adPlacements": [{"ad": "spam"}], "playerAds": [1], '
        '"adSlots": [], "adBreakHeartbeatParams": "token123", '
        '"adSlotRenderer": {}, "primetimeMastheadRenderer": {}}'
    )
    modified, new_payload = strip_youtube_ads(payload_ads)
    assert modified is True
    assert '"adPlacements_BLOCKED"' in new_payload
    assert '"playerAds_BLOCKED"' in new_payload
    assert '"adSlots_BLOCKED"' in new_payload
    assert '"adBreakHeartbeatParams_BLOCKED"' in new_payload
    assert '"adSlotRenderer_BLOCKED"' in new_payload
    assert '"primetimeMastheadRenderer_BLOCKED"' in new_payload
    assert '"adPlacements"' not in new_payload
    assert '"adBreakHeartbeatParams"' not in new_payload

    # Crucial regression test: YouTube topbar and search box must NEVER be blocked
    html_topbar = '<ytd-app><ytd-masthead id="masthead" slot="masthead"><div id="search-input"></div></ytd-masthead></ytd-app>'
    modified, new_topbar = strip_youtube_ads(html_topbar)
    assert modified is False
    assert 'id="masthead"' in new_topbar
    assert 'slot="masthead"' in new_topbar


