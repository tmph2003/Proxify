# Tài liệu Cập nhật: Kiến Trúc Phòng Thủ Chống Checkpoint (Zero Checkpoint Architecture) cho ProfileCrawler

## 1. Tóm tắt thay đổi
- **Loại bỏ 100% việc gửi Cookie từ Backend Python:** Xóa bỏ tham số `client_cookie` và cơ chế mang cookie người dùng gửi request từ `curl_cffi` trong `profile.py`.
- **Cơ chế phân giải URL trang cá nhân ẩn danh (Strictly Anonymous Slug Resolution):** Hàm `resolve_profile_id` chỉ gửi request vãng lai (Guest Mode) không header Cookie khi cần phân giải vanity slug thành Numeric ID. Nếu URL đã chứa Numeric ID hoặc `profile.php?id=...`, hàm trả về ngay mà không cần gửi bất kỳ request mạng nào.
- **Bắt buộc 100% Extension Bridge:** Trước khi cào Profile, kiểm tra nghiêm ngặt kết nối của Chrome Extension (`bridge.is_connected`). Nếu Extension offline, dừng ngay và cảnh báo người dùng, cấm tuyệt đối việc fallback cào bằng Python socket từ Docker.
- **Cảm biến ngắt khẩn cấp (Checkpoint Circuit Breaker):** Tích hợp hàm `_is_checkpoint_detected`. Nếu Facebook trả về bất kỳ dấu hiệu checkpoint hoặc yêu cầu xác minh tài khoản, hệ thống lập tức ngắt toàn bộ cào (`_stop_flag = True`) để bảo vệ tài khoản.
- **Nhịp độ người thật (Gaussian Human Pacing):** Áp dụng `page_delay(facade.delay_config)` với thời gian trễ ngẫu nhiên từ 2.0s - 8.0s giữa các trang cào timeline.

## 2. Mục đích & Ý nghĩa
- Ngăn chặn triệt để tình trạng Facebook kích hoạt cơ chế Checkpoint (956/282) do xung đột dấu vân tay mạng (TLS/Fingerprint Anomaly) giữa trình duyệt thật và Python backend.
- Bảo vệ an toàn tuyệt đối cho tài khoản Facebook của người dùng khi sử dụng chức năng cào bài viết từ trang cá nhân.

## 3. Mối liên hệ
- File chỉnh sửa: `backend/proxify/platforms/facebook/crawlers/profile.py`.
- Tương tác với: `CrawlerEngine` (`engine.py`), `ExtensionBridge` (`bridge.py`), và `CrawlDelayConfig` (`stealth.py`).

## 4. Rủi ro (Risks & Edge Cases)
- **Khi Extension chưa mở:** Nếu người dùng bấm cào mà chưa mở Chrome có tab Facebook, hệ thống sẽ từ chối cào và báo lỗi hướng dẫn. Đây là hành vi có chủ đích (Intentional Guardrail) để bảo vệ tài khoản.
