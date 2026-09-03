"""
Facebook Authentication & Token Management.
==========================================
Module này quản lý việc xác thực, kiểm tra trạng thái tài khoản và lưu trữ
bộ nhớ đệm In-Memory cho token/template:
1. Token & Template Store: IN_MEMORY_TEMPLATES lưu trên RAM (Zero-Disk Persistence)
2. Cookie Parser & Template Extractor: Chuẩn hóa cookies và templates
3. Auth & Checkpoint Verifier: Kiểm tra tính hợp lệ của cookie và trích xuất fb_dtsg/lsd qua HTML
"""

import logging
import os
import re
from typing import Optional, Tuple

from proxify.utils.stealth import StealthSessionManager

logger = logging.getLogger("proxify.facebook.auth")


# ─── 1. In-Memory Token & Template Store (Pure RAM) ──────────────────────────

IN_MEMORY_TEMPLATES = {}


def save_session_cache() -> None:
    """No-op: Toàn bộ phiên và template chỉ lưu trên RAM và localStorage.
    Tuyệt đối không lưu ra file đĩa hay DB.
    """
    pass


def load_session_cache() -> None:
    """No-op: Không đọc từ bất kỳ tệp đĩa nào."""
    pass


async def get_saved_tokens() -> Optional[dict]:
    """Lấy templates hiện có từ bộ nhớ RAM."""
    if IN_MEMORY_TEMPLATES:
        return IN_MEMORY_TEMPLATES
    return None


# ─── 2. Cookie & Template Helpers ────────────────────────────────────────────

def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Phân tích chuỗi cookie thô thành dictionary."""
    if not cookie_str:
        return {}

    separator = "," if "," in cookie_str and ";" not in cookie_str else ";"
    cookies: dict[str, str] = {}
    for pair in cookie_str.split(separator):
        if "=" in pair:
            k, v = pair.strip().split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def extract_templates(tokens: dict) -> Tuple[Optional[dict], Optional[dict], Optional[dict]]:
    """Trích xuất feed, comment, và reply templates từ dictionary tokens.

    Hỗ trợ cả định dạng phân cấp (nested format) và định dạng phẳng cũ (flat format).
    Returns:
        Tuple of (feed_template, comment_template, reply_template).
    """
    feed = tokens.get("feed")
    if isinstance(feed, dict) and "form_data" in feed:
        return (
            feed,
            tokens.get("comment"),
            tokens.get("reply"),
        )

    if "form_data" in tokens:
        return tokens, None, None

    return None, None, None


# ─── 3. Facebook Auth & Checkpoint Verifier ──────────────────────────────────

async def fetch_fb_auth_tokens(cookie_str: str, user_agent: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Xác minh tính hợp lệ của cookie và trích xuất fb_dtsg, lsd từ Facebook HTML.

    Returns:
        Tuple (fb_dtsg, lsd, error_message)
    """
    if not cookie_str:
        return None, None, "Cookie rỗng"

    if "c_user=" not in cookie_str:
        return None, None, "Cookie không hợp lệ. Phải chứa c_user=..."

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
        logger.info("[Auth] Đang kiểm tra cookie qua www.facebook.com...")
        resp = await manager.request("GET", "https://www.facebook.com/", headers=headers, allow_redirects=True, timeout=15)
        html = resp.text
        url_str = str(resp.url)

        if "checkpoint" in url_str:
            return None, None, "Cookie đã bị Facebook chặn (Checkpoint). Vui lòng gỡ checkpoint trên trình duyệt."
        if "login" in url_str or 'id="login_form"' in html or 'name="login"' in html:
            return None, None, "Cookie đã hết hạn (Bị đá ra trang Login). Vui lòng lấy lại Cookie mới từ trình duyệt."

        fb_dtsg = None
        fb_dtsg_patterns = [
            r'"DTSGInitialData",\[\],{"token":"([^"]+)"',
            r'DTSGInitData.*?token":"([^"]+)"',
            r'{"name":"fb_dtsg","value":"([^"]+)"}',
            r'name="fb_dtsg"\s*value="([^"]+)"',
            r'fb_dtsg\\" value=\\"([^\\"]+)\\"',
            r'\b(?:fb_dtsg|dtsg_token)["\']?\s*[:=]\s*["\']?([^"\'}&]+)',
        ]

        for pattern in fb_dtsg_patterns:
            match = re.search(pattern, html)
            if match:
                fb_dtsg = match.group(1)
                break

        lsd = None
        lsd_patterns = [
            r'"LSD",\[\],{"token":"([^"]+)"',
            r'LSD.*?token":"([^"]+)"',
            r'{"name":"lsd","value":"([^"]+)"}',
            r'name="lsd"\s*value="([^"]+)"',
            r'lsd\\" value=\\"([^\\"]+)\\"',
            r'\blsd["\']?\s*[:=]\s*["\']?([^"\'}&]+)',
        ]

        for pattern in lsd_patterns:
            match = re.search(pattern, html)
            if match:
                lsd = match.group(1)
                break

        if not fb_dtsg:
            try:
                os.makedirs("dumps", exist_ok=True)
                with open("dumps/fb_failed_auth.html", "w", encoding="utf-8") as f:
                    f.write(html)
                logger.error(f"[Auth] Không trích xuất được fb_dtsg. Đã lưu dump HTML vào dumps/fb_failed_auth.html ({len(html)} bytes)")
            except Exception as e:
                logger.error(f"[Auth] Lỗi khi lưu dump HTML: {e}")
            return None, None, "Không thể trích xuất fb_dtsg từ trang web. Có thể Facebook đã thay đổi giao diện hoặc cookie bị giới hạn."

        logger.info(f"[Auth] Lấy token thành công! fb_dtsg={fb_dtsg[:10]}..., lsd={lsd[:10] if lsd else 'None'}")
        return fb_dtsg, lsd, None

    except Exception as e:
        logger.error(f"[Auth] Lỗi khi fetch token: {e}")
        return None, None, f"Lỗi kết nối Facebook: {str(e)}"
