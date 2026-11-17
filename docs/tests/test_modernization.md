# Hiện Đại Hóa Bộ Kiểm Thử (Test Suite Modernization) - Đồng Bộ SQLite Storage

## 1. Tóm tắt thay đổi
Chúng tôi đã tiến hành rà soát và cập nhật 5 bài kiểm thử kế thừa (legacy tests) trong `backend/tests/test_retention.py` và `backend/tests/test_router_and_resilience.py` để loại bỏ hoàn toàn các mock phụ thuộc vào PostgreSQL (`psycopg2`, `asyncpg`) và đồng bộ chính xác với kiến trúc SQLite (`aiosqlite`, `sqlite3`):

1. **`test_repository_delete_old_requests_parameterized`** (`backend/tests/test_retention.py`):
   - Thay thế mock con trỏ dạng context manager (`conn.cursor.return_value.__enter__.return_value`) thành con trỏ trả về trực tiếp từ phương thức (`conn.cursor.return_value = mock_cur`) theo chuẩn giao diện `sqlite3.Cursor`.
   - Cập nhật placeholder tham số truy vấn từ cú pháp PostgreSQL (`%s`) sang cú pháp SQLite (`?`).
   - Bổ sung xác minh đóng con trỏ (`mock_cur.close.assert_called_once()`).

2. **`test_repository_delete_old_requests_backwards_compatible`** (`backend/tests/test_retention.py`):
   - Tương tự, cập nhật mock `conn.cursor()` trả về trực tiếp `mock_cur`.
   - Khẳng định truy vấn sử dụng placeholder `?` của SQLite và giải phóng con trỏ sau khi xóa.

3. **`test_ttl_worker_passes_configured_retention`** (`backend/tests/test_retention.py`):
   - Cập nhật vòng đời quản lý kết nối của `TTLWorker`: do SQLite trong `DatabasePool` sử dụng kiến trúc shared connection chế độ WAL thay vì connection pool đa luồng của PostgreSQL, phương thức `release_connection` là no-op và `TTLWorker.do_work()` không cần giải phóng kết nối về pool.
   - Chuyển assertion kiểm tra `get_connection()` được gọi và `delete_old_requests` thực thi đúng số ngày lưu trữ cấu hình.

4. **`test_database_manager_connect_retry_resilience`** (`backend/tests/test_router_and_resilience.py`):
   - Chuyển đổi đối tượng mock từ `asyncpg.create_pool` sang `aiosqlite.connect`.
   - Kiểm tra khả năng tự phục hồi (retry resilience) khi gặp lỗi (ví dụ file database bị lock), kiểm tra thiết lập PRAGMA (WAL, normal sync, busy timeout, foreign keys) và xác thực schema khởi tạo.
   - Bổ sung kiểm thử biên: kiểm tra `DatabaseManager` ném ngoại lệ chuẩn xác khi vượt quá số lần retry tối đa (`max_retries`).

5. **`test_database_pool_recreates_closed_pool`** (`backend/tests/test_router_and_resilience.py`):
   - Loại bỏ mock đối tượng `psycopg2.pool.ThreadedConnectionPool` và tham số DSN PostgreSQL không còn tồn tại.
   - Viết bài kiểm thử tích hợp thực tế với SQLite in-memory (`:memory:`) nhằm xác thực: khi kết nối `_conn` bị đóng (`close()`), lời gọi `get_connection()` hoặc context manager `connection()` tiếp theo sẽ tự động khởi tạo kết nối SQLite mới độc lập, duy trì tính sẵn sàng cao cho tầng lưu trữ.

---

## 2. Mục đích & Ý nghĩa
- **Giải quyết vấn đề**: Trước đây, sau khi dự án chuyển đổi tầng lưu trữ cơ sở dữ liệu từ PostgreSQL sang SQLite nội bộ (nhằm mục tiêu đóng gói standalone Windows `.exe` độc lập, không cần cài đặt dịch vụ database bên ngoài), các unit test tương ứng vẫn giữ nguyên mock của PostgreSQL và asyncpg. Điều này gây ra 5 lỗi kiểm thử nghiêm trọng (5 failing tests), làm gián đoạn pipeline CI/CD và che khuất các lỗi thực tế.
- **Tính xác thực (Authenticity)**: Các bài kiểm thử mới phản ánh chân thực 100% logic nghiệp vụ của `RequestRepository`, `TTLWorker`, `DatabaseManager`, và `DatabasePool`. Thay vì mock hời hợt hoặc giả lập kết quả, kiểm thử SQLite được thực thi trên môi trường Python 3.11 chuẩn với cả mock chính xác và tích hợp thực tế `:memory:`.

---

## 3. Mối liên hệ
- **`backend/proxify/core/traffic_storage/repository.py`**: Cung cấp logic thực thi truy vấn xóa bản ghi hết hạn `delete_old_requests`, đồng bộ bảng FTS5 và bảng `core_raw_payloads`.
- **`backend/proxify/core/traffic_storage/workers.py`**: Quản lý `TTLWorker` chạy nền để quét và dọn dẹp các traffic request đã quá hạn lưu trữ.
- **`backend/proxify/core/database.py`**: Quản lý kết nối bất đồng bộ `aiosqlite` cho proxy core và bảng `core_raw_payloads`, cơ chế tự động thử lại khi kết nối ban đầu thất bại.
- **`backend/proxify/database/connection.py`**: Quản lý kết nối đồng bộ SQLite (`DatabasePool`) phục vụ `RequestStorage` và Dashboard API với chế độ ghi WAL.
- **Pipeline kiểm thử toàn cục**: Đảm bảo bộ test suite backend (`backend/tests/`) và extension private (`private/tests/`) đạt tỷ lệ thành công 100% (56/56 tests passing).

---

## 4. Rủi ro (Risks & Edge Cases)
- **Cạnh tranh khóa SQLite (Lock Contention / Database Locked)**:
  - SQLite có thể gặp lỗi `sqlite3.OperationalError: database is locked` nếu nhiều tiến trình cùng ghi vào file database. `DatabaseManager` đã được cấu hình `PRAGMA busy_timeout=5000;` và `aiosqlite.connect(timeout=30.0)` cùng với cơ chế exponential retry. Bài test `test_database_manager_connect_retry_resilience` đã mô phỏng và bảo chứng việc xử lý ngoại lệ này thành công.
- **Tài nguyên bộ nhớ In-Memory**:
  - Khi sử dụng `:memory:` cho `DatabasePool`, nếu gọi `close()`, toàn bộ dữ liệu in-memory bị hủy hoàn toàn. Trong môi trường production, `DatabasePool` sử dụng đường dẫn file thật (`proxify.db`) do đó việc tái kết nối sẽ kết nối lại file dữ liệu hiện hữu mà không bị mất dữ liệu.
- **Đóng kết nối bất thường trong Thread Worker**:
  - Nếu `DatabasePool.close()` được gọi trong khi `TTLWorker` đang thực hiện truy vấn, worker có thể gặp lỗi tạm thời. Tuy nhiên worker có khối `try...except` ghi log và tiếp tục chu kỳ sau mà không làm sập ứng dụng.
