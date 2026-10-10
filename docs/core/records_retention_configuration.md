# Tài Liệu Kỹ Thuật: Cấu Hình & Cơ Chế Records Retention (TTL) Cho Traffic Storage

## 1. Tóm tắt thay đổi
- **Core Repository (`backend/proxify/core/traffic_storage/repository.py`)**:
  - Tái cấu trúc hàm `delete_old_requests`: Chuyển từ việc hardcode chuỗi SQL `INTERVAL '{interval}'` sang parameterized query `DELETE FROM requests WHERE timestamp_epoch < %s;`.
  - Tính toán `cutoff_epoch = time.time() - (retention_days * 86400.0)` tại Python runtime để tận dụng triệt để B-tree index `idx_requests_timestamp` trên cột `timestamp_epoch` (`DOUBLE PRECISION`), tránh tính toán động row-by-row bằng function trong PostgreSQL.
  - Tích hợp thêm dọn dẹp các bản ghi thô đã được xử lý trong bảng `core.raw_payloads`: `DELETE FROM core.raw_payloads WHERE processed = TRUE AND created_at < NOW() - (%s * INTERVAL '1 day');`.
  - Duy trì backwards compatibility: Nếu truyền tham số cũ dạng string `interval="7 days"`, hàm tự động parse số ngày an toàn bằng regex.
- **Background Worker (`backend/proxify/core/traffic_storage/workers.py`)**:
  - `TTLWorker` nhận tham số `retention_days: int = 7` (mặc định 7 ngày) từ dependency injection, lưu thành instance attribute và truyền vào repository trong chu kỳ dọn dẹp định kỳ (mỗi 1 giờ).
- **Service Orchestrator (`backend/proxify/core/traffic_storage/__init__.py`)**:
  - Bổ sung helper `parse_retention_days(val, default=7)` nhằm chuẩn hóa input từ biến môi trường hoặc API (chấp nhận số `7`, chuỗi `"7"`, `"7 days"`, `"7d"`, chặn số âm hoặc 0).
  - Khởi tạo `RequestStorage` đọc cấu hình từ biến môi trường `RECORD_RETENTION_DAYS` (hoặc `RETENTION_DAYS`), fallback về mặc định 7 ngày.
  - Expose property `retention_days` trên `RequestStorage` cho phép kiểm tra và cập nhật runtime động cho cả storage lẫn `ttl_worker`.
- **Dashboard API (`backend/proxify/dashboard.py`)**:
  - Endpoint `GET /api/config`: Trả về `retention_days` đang áp dụng.
  - Endpoint `POST /api/toggle_db`: Cho phép client/admin cập nhật `retention_days` ngay trong phiên làm việc mà không cần restart server.
- **Hạ tầng & Cấu hình Docker (`docker-compose.yml`, `.env`, `.env.example`)**:
  - Khai báo biến môi trường `RECORD_RETENTION_DAYS=7` trong file mẫu và file cấu hình thực tế.
  - Truyền biến môi trường `- RECORD_RETENTION_DAYS=${RECORD_RETENTION_DAYS:-7}` vào container `proxify_app` qua `docker-compose.yml`.
- **Kiểm thử tự động (`backend/tests/test_retention.py`)**:
  - Bổ sung 5 unit/integration test bao phủ toàn bộ luồng: parser, parameterized SQL execution, backwards compatibility, worker invocation, và dashboard async API.

---

## 2. Mục đích & Ý nghĩa
- **Vạch trần và xóa bỏ Technical Debt cũ**:
  - Hệ thống trước đây *đã có* worker dọn dẹp (`TTLWorker`), nhưng bị **hardcode cứng 3 ngày** (`interval: str = '3 days'`), hoàn toàn không thể cấu hình qua `.env` hay Dashboard.
  - Câu truy vấn SQL cũ dùng f-string nội suy chuỗi `INTERVAL '{interval}'` tiềm ẩn rủi ro SQL Injection nếu đầu vào không được kiểm soát chặt chẽ, đồng thời ép PostgreSQL phải parse lại chuỗi date/time thay vì nhận dạng kiểu dữ liệu nguyên thủy.
- **Tuân thủ Clean Architecture & SOLID**:
  - **Single Responsibility Principle (SRP)**: `repository.py` chỉ làm nhiệm vụ Data Access bằng câu lệnh truy vấn tham số hóa; logic parse/validate cấu hình được tách thành `parse_retention_days`; luồng hẹn giờ chạy nền thuộc về `TTLWorker`.
  - **Dependency Injection**: `retention_days` được bơm từ ngoài vào qua biến môi trường hoặc constructor thay vì hardcode bên trong domain service.
- **Tối ưu hóa hiệu năng Database Indexing**:
  - Bảng `public.requests` dùng `timestamp_epoch` (float epoch). Khi so sánh trực tiếp `timestamp_epoch < cutoff_epoch`, PostgreSQL sử dụng Index Range Scan với độ phức tạp $O(\log N)$, tránh việc quét toàn bảng (Full Table Scan) hoặc ép kiểu liên tục khi lưu lượng proxy lên đến hàng triệu requests.

---

## 3. Mối liên hệ
- **Mitmproxy Engine (`backend/proxify/server.py`)**:
  - Khởi tạo `RequestStorage` với retention 7 ngày mặc định.
- **Database Module (`backend/proxify/database/pool.py`)**:
  - Cung cấp kết nối từ pool cho `TTLWorker` để chạy chu kỳ xóa rác.
- **Dashboard Service (`backend/proxify/dashboard.py`)**:
  - Cung cấp giao diện quản trị thông tin trạng thái DB và retention.
- **Docker Compose**:
  - Đồng bộ cấu hình triển khai qua file môi trường `.env`.

---

## 4. Rủi ro (Risks & Edge Cases)
1. **Khối lượng bản ghi cần xóa quá lớn (Long-running Transaction Lock)**:
   - *Rủi ro:* Nếu proxy hoạt động thời gian dài mà retention bị tắt hoặc vừa đổi từ 30 ngày xuống 7 ngày, lệnh `DELETE` có thể xóa hàng trăm ngàn dòng trong một transaction duy nhất, gây lock bảng và phình transaction log (WAL).
   - *Biện pháp hiện tại & định hướng:* Lệnh delete chạy trên connection riêng của `TTLWorker` trong background thread với tần suất 1 lần/giờ. Về lâu dài khi lượng request đạt quy mô enterprise (hàng chục GB/ngày), nên cân nhắc chuyển sang partition table theo ngày (`PARTITION BY RANGE (timestamp_epoch)`) để thao tác `DROP TABLE` tức thời thay vì `DELETE`.
2. **Xung đột cấu hình runtime**:
   - *Rủi ro:* Cập nhật qua Dashboard API `POST /api/toggle_db` sẽ thay đổi giá trị in-memory của `storage.retention_days` và `ttl_worker.retention_days`, nhưng không tự động ghi đè file `.env`. Nếu container restart, cấu hình sẽ revert về giá trị trong `.env`.
   - *Khuyến cáo:* Đối với cấu hình cố định dài hạn, luôn thiết lập trong `.env` (`RECORD_RETENTION_DAYS=7`).
