# Tài liệu: `connection.py`

## 1. Tóm tắt tổng quan
File định nghĩa cấu trúc và logic quản lý các kết nối tới PostgreSQL thông qua `psycopg2.pool.ThreadedConnectionPool`. File cung cấp lớp `DatabasePool` nhằm tối ưu và bảo vệ kết nối trong môi trường đa luồng.

## 2. Mục đích & Ý nghĩa
Giúp thiết lập kết nối an toàn trong các ứng dụng multi-thread, tự động cấp phát và thu hồi kết nối thông qua các Context Manager (`with ...`). Điều này giúp lập trình viên không phải quan tâm tới việc rò rỉ kết nối (connection leak), đồng thời cho phép cấu hình giới hạn số lượng kết nối tối đa/tối thiểu qua các tham số.

## 3. Mối liên hệ
- **Được gọi bởi:** File `__init__.py` trong cùng thư mục `database` sử dụng `DatabasePool` để khởi tạo biến `pool` dùng chung.
- **Sử dụng:** Tương tác chặt chẽ với thư viện `psycopg2` để thao tác trực tiếp với PostgreSQL. 

## 4. Rủi ro (Risks & Edge Cases)
- **Cạn kiệt Pool (Pool Exhaustion):** Nếu số lượng kết nối đang sử dụng (và chưa trả về) vượt quá giới hạn `max_conn=5`, ứng dụng sẽ không thể lấy thêm kết nối, gây nghẽn cổ chai (bottleneck) hoặc treo ứng dụng.
- **Xử lý Exception:** Nếu kết nối DB bị mất giữa chừng (network partition, DB restart), các lệnh đang chạy có thể raise Exception mà pool không tự phục hồi ngay, hàm `get_connection` có thể return `None` gây lỗi ở `ContextManager`.
- **Thiết lập Autocommit:** File thiết lập mặc định `conn.autocommit = True`, nên mọi truy vấn thay đổi dữ liệu sẽ commit ngay lập tức. Cần lưu ý nếu module nào đó cần quản lý transaction bằng tay.

## 5. Chi tiết các Class và Hàm

- **Biến toàn cục:**
  - `DB_DSN`: Chuỗi cấu hình kết nối PostgreSQL, mặc định lấy từ biến môi trường `DB_DSN` hoặc giá trị mặc định nội bộ.
  - `logger`: Đối tượng log của `proxify`.

- **Class `DatabasePool`:**
  - `__init__(self, dsn: str, min_conn: int, max_conn: int)`: Phương thức khởi tạo. Gán các thông số cấu hình và để `_pool` là `None` (lazy initialization).
  - `_ensure_pool(self) -> pool.ThreadedConnectionPool | None`: Hàm nội bộ để khởi tạo `ThreadedConnectionPool` (lazy init). Nếu bị lỗi kết nối, nó ghi log lỗi và trả về `None`.
  - `get_connection(self)`: Xin một kết nối từ pool. Bật sẵn tính năng `autocommit=True` cho kết nối đó. Trả về `None` nếu có lỗi.
  - `release_connection(self, conn)`: Trả lại kết nối vào pool sau khi đã dùng xong (bằng `putconn`). Bỏ qua lỗi trong quá trình thu hồi nếu có.
  - `connection(self)`: Một `contextmanager` để sử dụng dưới dạng `with pool.connection() as conn:`. Lấy connection tự động và đảm bảo nó được release ở block `finally`. Sẽ ném ra `ConnectionError` nếu không kết nối được.
  - `cursor(self, dict_cursor: bool = False)`: Một `contextmanager` tiện ích khác (sử dụng `connection()` ở trên), trả về đối tượng `cursor`. Nếu cờ `dict_cursor=True`, sẽ dùng `RealDictCursor` giúp kết quả query trả về dạng dictionary thay vì tuple.
  - `ensure_schema(self, schema_name: str)`: Hàm giúp tự động kiểm tra và tạo schema PostgreSQL nếu chưa có (e.g. schema cho zalo, facebook). Giúp tự động thiết lập ban đầu.
  - `close(self)`: Gọi lệnh `closeall()` để đóng toàn bộ các kết nối trong pool một cách dọn dẹp. Dùng khi ứng dụng shutdown.
