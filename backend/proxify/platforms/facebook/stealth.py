"""
Facebook Stealth Engine — Hợp nhất các cơ chế tàng hình & phòng thủ chống Bot.
=============================================================================
Module này gom nhóm toàn bộ các logic:
1. Nhịp điệu & Độ trễ hành vi con người (CrawlDelayConfig, Gaussian delay)
2. Đột biến tham số phiên động (SessionStateManager: __req, __s, __spin_t)
3. Điều phối tốc độ mạng toàn cục (GlobalNetworkClient: Borg Pattern Rate Limiter)
"""

import asyncio
import random
import string
import time
from dataclasses import dataclass
from typing import Optional

from proxify.utils.stealth import StealthSessionManager


# ─── 1. Chiến Lược Độ Trễ Giả Lập Hành Vi Con Người (Gaussian Timing) ───────

@dataclass(frozen=True)
class CrawlDelayConfig:
    """Cấu hình độ trễ giả lập hành vi con người.

    Sử dụng phân phối chuẩn Gaussian kẹp biên [min, max] để tránh bị phát hiện
    dấu hiệu máy móc (Uniform distribution signature).
    """

    # Độ trễ giữa các trang (phân trang feed)
    page_mean: float = 4.0
    page_std: float = 1.5
    page_min: float = 2.0
    page_max: float = 8.0

    # Độ trễ giữa các lượt cào bình luận/phản hồi con (Ngưỡng tự nhiên tránh bị đánh dấu bot)
    comment_mean: float = 2.5
    comment_std: float = 0.8
    comment_min: float = 1.5
    comment_max: float = 5.0

    # Xác suất xuất hiện khoảng dừng lâu (mô phỏng người dùng đọc bài viết/bình luận)
    long_pause_chance: float = 0.10
    long_pause_min: float = 5.0
    long_pause_max: float = 15.0


DEFAULT_DELAY_CONFIG = CrawlDelayConfig()


def _gaussian_clamped(mean: float, std: float, lo: float, hi: float) -> float:
    """Lấy mẫu từ phân phối chuẩn Gaussian, kẹp chặt trong khoảng [lo, hi]."""
    return max(lo, min(hi, random.gauss(mean, std)))


def page_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float:
    """Tính toán thời gian nghỉ tự nhiên giữa các trang cào bài viết."""
    delay = _gaussian_clamped(
        config.page_mean, config.page_std, config.page_min, config.page_max,
    )
    if random.random() < config.long_pause_chance:
        delay += random.uniform(config.long_pause_min, config.long_pause_max)
    return delay


def comment_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float:
    """Tính toán thời gian nghỉ tự nhiên giữa các lượt cào bình luận."""
    delay = _gaussian_clamped(
        config.comment_mean, config.comment_std, config.comment_min, config.comment_max,
    )
    if random.random() < 0.05:
        delay += random.uniform(3.0, 7.0)
    return delay


# ─── 2. Đột Biến Dữ Liệu Phiên Động (Session State Mutation) ──────────────────

class SessionStateManager:
    """Quản lý các tham số form động của Facebook để mô phỏng phiên trình duyệt thật.

    Facebook kiểm tra:
        - `__req`: Bộ đếm số thứ tự request (mã hóa Base36, bắt buộc phải tăng dần)
        - `__s`: Session token ngẫu nhiên (thay đổi sau mỗi request)
        - `__spin_t`: Unix timestamp thời gian thực
    """

    _ALPHABET = string.digits + string.ascii_lowercase

    def __init__(self, counter_offset: Optional[int] = None) -> None:
        self._counter_offset = counter_offset if counter_offset is not None else random.randint(5, 15)
        self._request_count = 0

    def update_params(self, data: dict) -> None:
        """Đột biến trực tiếp các tham số __req, __s, __spin_t trong dict form_data."""
        counter = self._counter_offset + self._request_count
        data["__req"] = self._encode_base36(counter)
        if "__s" not in data or not data["__s"]:
            data["__s"] = self._gen_session_token()
        data["__spin_t"] = str(int(time.time()))
        self._request_count += 1

    @property
    def request_count(self) -> int:
        return self._request_count

    def reset(self) -> None:
        """Khởi động lại bộ đếm khi bắt đầu phiên cào mới."""
        self._counter_offset = random.randint(5, 15)
        self._request_count = 0

    @classmethod
    def _encode_base36(cls, n: int) -> str:
        if n == 0:
            return "0"
        chars = cls._ALPHABET
        parts: list[str] = []
        while n > 0:
            parts.append(chars[n % 36])
            n //= 36
        return "".join(reversed(parts))

    @staticmethod
    def _gen_session_token() -> str:
        pool = string.ascii_lowercase + string.digits

        def _part() -> str:
            return "".join(random.choices(pool, k=6))

        return f"{_part()}:{_part()}:{_part()}"


# ─── 3. Điều Phối Mạng Toàn Cục (Borg Rate Limiter) ──────────────────────────

class GlobalNetworkClient:
    """Borg pattern: Mọi instance đều chia sẻ chung một bộ nhớ trạng thái.

    Đảm bảo kiểm soát tốc độ mạng toàn cục và không có 2 request mạng nào
    tới Facebook chạy đè lên nhau cùng lúc.
    """
    _shared_state = {}

    def __init__(self, manager: Optional[StealthSessionManager] = None):
        self.__dict__ = self._shared_state
        if not hasattr(self, 'initialized'):
            self.manager = manager or StealthSessionManager(
                impersonate="chrome120", max_retries=2, base_delay=3.0, timeout=15.0,
            )
            self._rate_limit_lock = asyncio.Lock()
            self._last_request_time = 0.0
            self.initialized = True
        elif manager is not None:
            self.manager = manager

    async def safe_request(self, *args, **kwargs):
        """Bọc quanh manager.request với Mutex Lock và kiểm soát tốc độ tối thiểu 2.5s."""
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < 2.5:
                await asyncio.sleep(2.5 - elapsed)

            try:
                return await self.manager.request(*args, **kwargs)
            finally:
                self._last_request_time = time.time()
