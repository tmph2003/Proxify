import re
import logging
from typing import Tuple, Optional
from proxify.utils.stealth import StealthSessionManager

logger = logging.getLogger("proxify.auth_fetcher")

async def fetch_fb_auth_tokens(cookie_str: str, user_agent: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetches fb_dtsg and lsd from Facebook using the provided cookie.
    Returns (fb_dtsg, lsd, error_message)
    """
    if not cookie_str:
        return None, None, "Cookie rỗng"
        
    if "c_user=" not in cookie_str or "xs=" not in cookie_str:
        return None, None, "Cookie không hợp lệ. Bạn copy thiếu hoặc sai định dạng. Phải có c_user=... và xs=..."
        
    headers = {
        "cookie": cookie_str,
        "user-agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "navigate",
        "sec-fetch-user": "?1",
        "sec-fetch-dest": "document",
    }
    
    try:
        manager = StealthSessionManager()
        logger.info("[AuthFetcher] Đang kiểm tra cookie qua www.facebook.com...")
        resp = await manager.request("GET", "https://www.facebook.com/", headers=headers, allow_redirects=True, timeout=15)
        html = resp.text
        url_str = str(resp.url)
        
        if "checkpoint" in url_str:
            return None, None, "Cookie đã bị Facebook chặn (Checkpoint). Vui lòng gỡ checkpoint trên trình duyệt."
        if "login" in url_str or 'id="login_form"' in html or 'name="login"' in html:
            return None, None, "Cookie đã hết hạn (Bị đá ra trang Login). Vui lòng lấy lại Cookie mới từ trình duyệt."
            
        fb_dtsg_match = re.search(r'"DTSGInitialData",\[\],{"token":"([^"]+)"', html)
        if not fb_dtsg_match:
            fb_dtsg_match = re.search(r'name="fb_dtsg"\s*value="([^"]+)"', html)
            
        lsd_match = re.search(r'"LSD",\[\],{"token":"([^"]+)"', html)
        if not lsd_match:
            lsd_match = re.search(r'name="lsd"\s*value="([^"]+)"', html)
            
        fb_dtsg = fb_dtsg_match.group(1) if fb_dtsg_match else None
        lsd = lsd_match.group(1) if lsd_match else None
        
        if not fb_dtsg:
            return None, None, "Không thể trích xuất fb_dtsg từ trang web. Có thể Facebook đã thay đổi giao diện hoặc cookie bị giới hạn."
            
        logger.info(f"[AuthFetcher] Lấy token thành công! fb_dtsg={fb_dtsg[:10]}..., lsd={lsd[:10] if lsd else 'None'}")
        return fb_dtsg, lsd, None
            
    except Exception as e:
        logger.error(f"[AuthFetcher] Lỗi khi fetch token: {e}")
        return None, None, f"Lỗi kết nối Facebook: {str(e)}"
