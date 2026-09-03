# Tài Liệu Kỹ Thuật: Module `backend/proxify/platforms/facebook/workflow.py`

## 1. Tóm tắt thay đổi
- **Hợp nhất mã nguồn**:
  - Gom toàn bộ logic từ `commands.py`, `observer.py`, và `queue_manager.py` vào một module điều phối tác vụ duy nhất: `workflow.py`.
- **Thành phần cốt lõi**:
  - **Command Pattern**: Đóng gói các yêu cầu cào thành đối tượng có thể xếp hàng và thực thi trì hoãn:
    - `BaseCommand` (lớp trừu tượng)
    - `RefreshCommand` (làm mới số liệu bài viết cụ thể)
    - `CrawlFeedCommand` (cào bảng tin nhóm theo mốc thời gian và cursor)
    - `CrawlCommentCommand` (cào bình luận và phản hồi phân cấp)
  - **Observer Pattern**:
    - `CrawlerStateObserver` (`state_observer`): Theo dõi và cập nhật trạng thái tác vụ cào (tiến độ, số bài viết tìm thấy, trạng thái lỗi) phục vụ cho Web Dashboard hiển thị real-time qua WebSocket.
  - **Task Queue & Crash Recovery**:
    - `SQLiteQueueManager`: Quản lý hàng đợi tác vụ độc lập bằng SQLite cục bộ (`aiosqlite`). Hỗ trợ Dead-Letter Queue (DLQ), trạng thái `pending`, `processing`, `completed`, `failed` và khả năng tự phục hồi khi server khởi động lại.

---

## 2. Mục đích & Ý nghĩa
- **Tách biệt phát lệnh và thực thi (Decoupling)**: Dashboard API chỉ cần đẩy command vào hàng đợi, không cần chờ crawler hoàn thành.
- **Khả năng phục hồi cao (Resilience)**: Lưu hàng đợi trên SQLite cục bộ giúp crawler có thể tiếp tục công việc dang dở ngay cả khi server bị restart hoặc PostgreSQL tạm thời ngắt kết nối.

---

## 3. Mối liên hệ
- Nhận lệnh từ `api.py` (`FacebookAPI`).
- Điều phối thực thi thông qua `crawler.py` (`FacebookCrawler`).
- Bắn trạng thái tiến độ tới UI Dashboard qua `state_observer`.

---

## 4. Rủi ro & Edge Cases
- **SQLite Locking**: Sử dụng `aiosqlite` với cơ chế async context manager và WAL mode để tránh lỗi `database is locked` khi có nhiều luồng đọc ghi hàng đợi cùng lúc.
