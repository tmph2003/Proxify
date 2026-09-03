# Tài Liệu Kỹ Thuật: Module `backend/proxify/platforms/facebook/stealth.py`

## 1. Tóm tắt thay đổi
- **Hợp nhất mã nguồn**:
  - Gom toàn bộ logic từ `delay.py`, `session_state.py`, và `network.py` thành một module phòng thủ chống Bot duy nhất: `stealth.py`.
- **Thành phần cốt lõi**:
  - `CrawlDelayConfig`: Chiến lược độ trễ ngẫu nhiên theo phân phối chuẩn Gaussian (`page_delay`, `comment_delay`) kèm khoảng dừng dài (`long_pause_chance`) mô phỏng hành vi đọc bài của người thật.
  - `SessionStateManager`: Quản lý bộ đếm request nội bộ của Facebook (`__req`, `__s`, `__spin_t`, `__spin_b`, `__spin_r`), tự động tăng biến số tương tự như JavaScript engine của trình duyệt thực thụ.
  - `GlobalNetworkClient` (Borg Pattern): Chia sẻ chung trạng thái khóa `asyncio.Lock` và `last_request_time`, ép buộc khoảng cách giữa 2 request bất kỳ tới Facebook luôn **≥ 2.5s** (Global Mutex Rate Limiter).

---

## 2. Mục đích & Ý nghĩa
- **Vô hiệu hóa thuật toán phát hiện Bot của Facebook**:
  - Facebook sử dụng Machine Learning để phân tích nhịp request (Uniform vs Normal distribution). Sử dụng Gaussian delay kẹp biên giúp nhịp cào tự nhiên như người dùng cuộn chuột.
  - Việc đột biến tham số `__req` dạng hex (`1`, `2`, ..., `a`, `b`) loại bỏ dấu hiệu bất thường về thứ tự gói tin.
  - Khóa rate-limiter toàn cục đảm bảo ngay cả khi cào đa luồng (Feed + Comments), hệ thống vẫn không bao giờ bắn request ồ ạt gây khóa tài khoản hoặc dính lỗi 1357001.

---

## 3. Mối liên hệ
- Sử dụng tiện ích hạ tầng `StealthSessionManager` từ `proxify.utils.stealth`.
- Được `crawler.py` (`FacebookCrawler`) sử dụng xuyên suốt mọi vòng lặp phân trang và truy xuất dữ liệu.

---

## 4. Rủi ro & Edge Cases
- **Tốc độ cào bị giới hạn**: Do tuân thủ nghiêm ngặt ngưỡng an toàn 2.5s và Gaussian pause, tốc độ cào sẽ chậm hơn so với cào brute-force thông thường, nhưng đảm bảo tài khoản sống bền vững và không bị checkpoint.
