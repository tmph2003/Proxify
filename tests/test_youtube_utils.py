import pytest
from proxify.utils.youtube_utils import is_youtube_ad_request, strip_youtube_ads

def test_is_youtube_ad_request():
    # True cases
    assert is_youtube_ad_request("https://youtube.com/api/stats/atr?adformat=1", "youtube.com")
    assert is_youtube_ad_request("https://youtube.com/pcs/activeview", "youtube.com")
    # False cases because domain check filters them out
    assert not is_youtube_ad_request("https://googleads.g.doubleclick.net/pagead/interaction/", "doubleclick.net")
    
    # False cases
    assert not is_youtube_ad_request("https://youtube.com/watch?v=123", "youtube.com")
    assert not is_youtube_ad_request("https://example.com/api/stats", "example.com")
    assert not is_youtube_ad_request("https://youtubei.googleapis.com/youtubei/v1/next", "youtubei.googleapis.com")

def test_strip_youtube_ads():
    # No ads case (returns False immediately because no ad keywords found)
    html_clean = "<html><body>Clean page</body></html>"
    modified, new_html = strip_youtube_ads(html_clean)
    assert modified is False
    
    # Anti-AFK injection requires one of the ad keywords to be present to pass the early exit
    html_with_ad_keyword = '<html><body>{"adSlots": []}</body></html>'
    modified, new_html = strip_youtube_ads(html_with_ad_keyword)
    assert modified is True
    assert "Anti-AFK" in new_html
    
    # Ads case
    html_ads = '{"adPlacements": [{"ad": "spam"}], "playerAds": [1]}'
    modified, new_html = strip_youtube_ads(html_ads)
    assert modified is True
    assert '"adPlacements_BLOCKED"' in new_html
    assert '"playerAds_BLOCKED"' in new_html
    assert '"adPlacements"' not in new_html
