# Tài Liệu Kỹ Thuật: Module `backend/proxify/core/traffic_storage/`

## 1. Tóm tắt thay đổi
- **Quy hoạch kiến trúc**:
  - Di chuyển toàn bộ thư mục `backend/proxify/storage/` thành `backend/proxify/core/traffic_storage/`.
  - Xóa bỏ hoàn toàn thư mục cũ `backend/proxify/storage/` để tránh phân mảnh và dư thừa.
- **Cập nhật Import toàn hệ thống**:
  - `backend/proxify/server.py`: Chuyển `from proxify.storage import RequestStorage` thành `from proxify.core.traffic_storage import RequestStorage`.
  - `backend/proxify/dashboard.py`: Chuyển `from proxify.storage import RequestStorage` thành `from proxify.core.traffic_storage import RequestStorage`.
  - Chuẩn hóa logger namespace: `proxify.core.traffic_storage`, `proxify.core.traffic_storage.repository`, `proxify.core.traffic_storage.workers`.

---

## 2. Mục đích & Ý nghĩa
- **Khắc phục dứt điểm Naming Smell**: Trước đây, cái tên `storage` ở tầng root dễ gây ngộ nhận rằng đây là lớp Data Access chung cho toàn bộ dự án.
- **Phân định rạch ròi theo Clean Architecture**:
  - `backend/proxify/database/`: Là **Infrastructure Connection Pool** (`psycopg2.pool.ThreadedConnectionPool`) dùng chung cho toàn bộ ứng dụng (Facebook, Zalo, Traffic Storage).
  - `backend/proxify/core/traffic_storage/`: Là **Domain Service của Core Proxy Engine** chuyên trách ghi nhận, batch commit (`AsyncWriterWorker`) và quản lý vòng đời TTL (`TTLWorker`) cho các gói tin HTTP/HTTPS của Mitmproxy vào bảng `public.requests`.
- Gom `traffic_storage` vào bên trong `core/` giúp cấu trúc thư mục tự giải thích (Self-explanatory) và thể hiện đúng quan hệ phụ thuộc.

---

## 3. Mối liên hệ
- Sử dụng `shared_pool` từ `proxify.database.pool` để thực thi truy vấn SQL.
- Phục vụ API truy vấn dữ liệu cho `Dashboard` (`dashboard.py`) để hiển thị danh sách request, lọc theo domain, xem chi tiết headers/body.

---

## 4. Rủi ro & Kiểm thử
- **Rủi ro:** Xung đột import đường dẫn cũ.
- **Giải pháp xử lý:** Đã quét toàn bộ dự án, không còn bất kỳ file nào gọi tới `proxify.storage`.
- **Kiểm thử tự động:**
  - Import module độc lập: Thành công `TRAFFIC_STORAGE IMPORT OK!`.
  - Chạy toàn bộ test suite `pytest tests/`: **37/37 tests PASSED 100%**.
