# Tài liệu: `proxify/platforms/facebook/queue_manager.py`

## 1. Tóm tắt tổng quan
File `queue_manager.py` cung cấp cơ chế hàng đợi (task queue) sử dụng SQLite (thư viện `aiosqlite`) làm backend lưu trữ. Nó quản lý các tác vụ thu thập, đảm bảo các yêu cầu được xếp hàng, không bị mất khi ứng dụng khởi động lại, và cung cấp khả năng tự động thử lại (retry) hoặc đẩy tác vụ lỗi vào Dead Letter Queue (DLQ).

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Thay vì lưu hàng đợi trên bộ nhớ (RAM) hoặc dùng Redis phức tạp, SQLiteQueueManager cung cấp một hàng đợi bền vững (persistent) ngay trong file nội bộ (queue.db).
- **Ý nghĩa**: Đảm bảo Zero Data Loss. Nếu ứng dụng hoặc server bị tắt đột ngột, các lệnh thu thập vẫn còn đó và sẽ chạy tiếp khi khởi động lại. Nó giúp thiết lập ứng dụng cực kỳ đơn giản (chỉ chạy là xong, không cần cài Redis).

## 3. Mối liên hệ
- Nó được thiết kế để thay thế hoặc bổ trợ cho các luồng xử lý yêu cầu Command trong tương lai của Facebook Crawler, hoặc các worker bất đồng bộ cần quản lý tác vụ dài hạn.
- Gọi trực tiếp module `aiosqlite` để giao tiếp với file DB bất đồng bộ.

## 4. Rủi ro (Risks & Edge Cases)
- **Tốc độ SQLite (Disk I/O)**: Bị giới hạn bởi tốc độ ghi/đọc ổ cứng, không phù hợp cho các queue cần tốc độ tới hạn (hàng ngàn task/giây). Nhưng cho crawler (vài chục task/phút) thì rất tốt.
- **File DB phình to**: Hàm `clear()` có hỗ trợ xóa nhưng nếu không có worker dọn rác (Cleanup Worker), các tác vụ completed hoặc failed sẽ ngày một phình to làm chậm DB.
- **Concurrency Locking**: Vì sử dụng `asyncio.Lock()`, các thao tác get/put đều phải chờ nhau. Dễ gây chậm (latency) nhẹ ở cấp độ phần mềm.

## 5. Chi tiết các Class và Hàm

### 1. `SQLiteQueueManager` (Class)
- **Mô tả**: Bộ quản lý hàng đợi dựa trên SQLite.
- **Thuộc tính**:
  - `db_path`: Đường dẫn tới file database SQLite (mặc định "queue.db").
  - `_lock`: Cơ chế khóa của `asyncio` để tránh xung đột I/O.

- **Các hàm**:
  - `__init__(self, db_path: str = "queue.db")`: Khởi tạo đường dẫn và khóa.
  - `async def init_db(self)`: Tạo bảng `queue` nếu chưa có. Khôi phục (reset) các tác vụ đang chạy dở (status='processing') về lại trạng thái chờ (status='pending') để xử lý lại (đề phòng crash).
  - `async def put(self, task_type: str, payload: Dict[str, Any], max_retries: int = 3)`: Chuyển dữ liệu thành chuỗi JSON và chèn một dòng tác vụ mới vào bảng.
  - `async def get(self) -> Optional[Dict[str, Any]]`: Lấy (Dequeue) một tác vụ có trạng thái `pending` cũ nhất (ASC theo id). Nếu lấy được, chuyển trạng thái thành `processing` và trả về một dict thông tin.
  - `async def task_done(self, task_id: int)`: Đánh dấu một tác vụ đã hoàn tất (status='completed').
  - `async def retry_task(self, task_id: int, reason: str)`: Tăng biến đếm `retries`. Nếu còn trong giới hạn `max_retries`, chuyển trạng thái về `pending` để chờ chạy lại. Nếu vượt quá số lần cho phép, chuyển thành `failed` (Dead Letter Queue).
  - `async def get_progress(self) -> dict`: Đếm số lượng tác vụ gom nhóm theo từng trạng thái (pending, processing, completed, failed, total).
  - `async def clear(self)`: Xóa toàn bộ dữ liệu trong bảng `queue`.
