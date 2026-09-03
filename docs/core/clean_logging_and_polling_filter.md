# Tài Liệu Kỹ Thuật: Chuẩn Hóa Hệ Thống Logger & Bộ Lọc Polling Spam (Clean Logging)

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/server.py`
  - `backend/proxify/platforms/facebook/api.py`
  - `backend/proxify/platforms/facebook/bridge.py`
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/proxify/platforms/facebook/extractor.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Bộ lọc Access Log cho Polling Endpoints (`server.py`):**
   - Xây dựng lớp `PollingEndpointFilter(logging.Filter)` gắn trực tiếp vào `aiohttp.access`.
   - Tự động bỏ qua các dòng log HTTP `200/304 OK` phát sinh từ polling định kỳ (1-2s/lần) của frontend và extension:
     - `/api/facebook/bridge/jobs`
     - `/api/facebook/bulk_status`
     - `/api/facebook/crawl_status`
     - `/api/facebook/comment_status`
     - `/api/facebook/cookie`
     - `/api/stats`, `/api/status`, `/ws`
   - Vẫn giữ nguyên hiển thị log nếu có lỗi HTTP 4xx hoặc 5xx.

2. **Xóa bỏ Data Dump & Hạ cấp Log Heartbeat (`api.py`, `bridge.py`):**
   - Xóa bỏ hoàn toàn log `FULL DATA DUMP` (từng dump hàng chục ngàn ký tự JSON thô mỗi 2 giây).
   - Hạ cấp các log đồng bộ cookie định kỳ, template extraction, bridge job dispatch/completion từ `INFO` xuống `DEBUG`.

3. **Làm sạch Log trong Crawler & Extractor (`crawler.py`, `extractor.py`):**
   - Chuyển log kiểm tra kết nối bridge từng request, log phân giải fallback cookie, log tổng hợp template synthetic từ `INFO` xuống `DEBUG`.
   - Chuyển log bỏ qua bài viết không thuộc nhóm (Suggested posts) trong `extractor.py` xuống `DEBUG`.

---

## 2. Mục đích & Ý nghĩa

- **Giải quyết triệt để vấn đề "Ô nhiễm log" (Log Noise Pollution):** Terminal trước đây bị tràn ngập hàng trăm dòng log spam mỗi phút, che lấp các sự kiện nghiệp vụ quan trọng.
- **Tối ưu hóa hiệu năng và I/O:** Giảm tải I/O ghi log không cần thiết trên Docker container.
- **Cải thiện trải nghiệm gỡ lỗi:** Giúp cả lập trình viên và AI theo dõi được luồng công việc thực tế (bắt đầu cào, tiến độ từng trang, số bài viết/bình luận đã trích xuất, cảnh báo lỗi thực tế) một cách trực quan và trong sáng.

---

## 3. Mối liên hệ kiến trúc

- **`proxify.server`:** Cấu hình bộ lọc cấp gốc cho server HTTP.
- **`platforms.facebook.api` / `bridge` / `crawler`:** Chuẩn hóa cấp độ log theo đúng chuẩn Domain Events vs Debug Internals.

---

## 4. Rủi ro & Giải pháp Kiểm soát

1. **Cần xem chi tiết log debug khi điều tra lỗi ngầm:**
   - *Giải pháp:* Thiết kế tuân thủ tiêu chuẩn Python logging. Khi cần xem chi tiết từng byte payload hoặc heartbeat, chỉ cần cấu hình `LOG_LEVEL=DEBUG` trong biến môi trường hoặc file `.env`.
