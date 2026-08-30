# AI Developer Changelog

File này ghi nhận toàn bộ các thay đổi về mặt kiến trúc, mã nguồn và sửa lỗi do AI thực hiện trong quá trình phát triển dự án Proxify.

## [2026-08-29] Chiến dịch Đại phẫu CSDL và Xử lý Lỗi Crawler Facebook

### 1. Vấn đề "Mismatched ID" giữa Frontend và Database
* **Tình trạng:** Crawler cào thành công nhưng lưu bài viết dưới ID số (Numeric ID). Tuy nhiên Dashboard của Frontend lại query bằng chữ (Slug), dẫn đến giao diện hiển thị rỗng.
* **Giải pháp (Refactor Cấu trúc DB):**
  * Thêm bảng `facebook.groups` (group_id, slug) làm bộ đệm cache tra cứu ID.
  * Thêm cột `group_numeric_id` vào bảng `facebook.posts` để lưu trữ song song với cột `group_id` (Slug).
  * Chạy Data Backfill script: Dịch ngược và cập nhật lại toàn bộ `group_numeric_id` cho các post đã lưu, đồng thời trả lại Slug gốc cho các post bị lưu sai.
* **Cập nhật mã nguồn:**
  * `proxify/platforms/facebook/database.py`: Bổ sung Schema bảng `facebook.groups` và cột `group_numeric_id`.
  * `proxify/platforms/facebook/repository.py`: Cập nhật logic `_do_upsert` để chèn thêm dữ liệu cho `group_numeric_id`.
  * `proxify/platforms/facebook/extractor.py`: Chỉnh sửa hàm `extract_from_responses` để lấy cả 2 định danh.
  * `proxify/platforms/facebook/crawler.py`: Nâng cấp hàm `_resolve_numeric_group_id` tự động tra cứu từ DB trước khi call API (giúp tiết kiệm Rate Limit của tài khoản).
  * `proxify/plugins/facebook.py`: Xóa bỏ hoàn toàn đoạn code dùng `aiohttp` tự ép kiểu Slug thành Số. Cập nhật hàm `_handle_facebook_results` để query kết quả thông qua cả `group_id` VÀ `group_numeric_id`.

### 2. Xử lý ảo giác lỗi "Can not decode content-encoding: br"
* **Tình trạng:** Người dùng báo lỗi văng 400 Bad Request liên quan đến giải mã Brotli (`br`) khi Crawler đang chạy phân giải URL.
* **Quá trình Debate / Phân tích:**
  * Xem xét việc ép bỏ header `"accept-encoding"` nhưng phát hiện điều này làm hỏng vân tay (Fingerprint) Chrome 120 của thư viện `curl_cffi`, rất dễ bị Facebook khóa tài khoản.
  * Xem xét việc cài thêm `brotli` qua Pip nhưng phát hiện rủi ro sập tiến trình do thiếu C++ Build Tools trên Windows.
* **Giải pháp:**
  * Phát hiện ra thư viện lõi `curl_cffi` bản chất đã hỗ trợ giải nén `brotli` ở tầng C++ nên không thể có lỗi này.
  * Lỗi này thực chất bộc phát từ thư viện `aiohttp` nằm ở chính đoạn code mà AI đã **xóa bỏ** ở bước 1 (trong file `plugins/facebook.py`).
  * Kết luận: Không cần can thiệp mã nguồn. Người dùng chỉ cần Restart Server (để xóa bộ nhớ RAM lưu bản code cũ) là giải quyết được triệt để.

---
*(Các thay đổi tiếp theo sẽ được append nối tiếp vào file này)*
