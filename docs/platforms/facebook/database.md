# Tài liệu: `proxify/platforms/facebook/database.py`

## 1. Tóm tắt tổng quan
File `database.py` là trung tâm Data Access Layer hoàn chỉnh cho nền tảng Facebook. Nó hợp nhất toàn bộ các lớp Repository (`AuthorRepository`, `PostRepository`, `CommentRepository`, `ConfigRepository`) cùng lớp Facade `FacebookDatabase`. Nó chịu trách nhiệm tự động khởi tạo schema (`facebook`), tạo bảng DDL, quản lý kết nối và cung cấp singleton `fb_db` cho toàn ứng dụng. File `repository.py` được chuyển thành module re-export để đảm bảo tương thích ngược 100%.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Hợp nhất Repository Pattern và Facade Pattern vào một file duy nhất, co-locate DDL schema và logic SQL INSERT/UPDATE tương ứng.
- **Ý nghĩa**: Giúp mã nguồn CSDL Facebook có tính gắn kết cực cao (High Cohesion), lập trình viên sửa bảng sẽ thấy ngay câu lệnh upsert ngay trong cùng file mà không phải nhảy qua lại giữa 2 file. Giảm phân mảnh mã nguồn mà vẫn giữ nguyên 100% tương thích ngược.

## 3. Mối liên hệ
- Sử dụng `shared_pool` và `DatabasePool` từ `proxify.database`.
- Tích hợp sẵn 4 Repository (`AuthorRepository`, `PostRepository`, `CommentRepository`, `ConfigRepository`) trực tiếp bên trong file.
- `repository.py` re-export các lớp từ `database.py` để tránh break code cũ.
- Đối tượng `fb_db` sinh ra ở cuối file này được import bởi toàn bộ `crawler.py`, `extractor.py`, `api.py`, `server.py` để lưu dữ liệu và cấu hình.

## 4. Rủi ro (Risks & Edge Cases)
- **Init chậm/Tắt nghẽn**: Khi có nhiều bảng và index, hàm `_init_tables` có thể mất thời gian chạy khi ứng dụng vừa khởi động. Nếu CSDL bị treo, toàn bộ ứng dụng sẽ treo ngay lúc import.
- **Xung đột khi nhiều Worker**: Nếu chạy đa tiến trình (multi-processing), nhiều worker sẽ cùng chạy lại lệnh CREATE TABLE / CREATE TRIGGER. Mặc dù có `IF NOT EXISTS`, vẫn có thể xảy ra race condition nhỏ với trigger.
- **Quản lý phiên bản DB**: Vì không dùng tool migration (như Alembic), nếu tương lai cấu trúc bảng thay đổi (sửa/xóa cột), lệnh `CREATE TABLE IF NOT EXISTS` sẽ không tự động cập nhật được (cần viết lệnh `ALTER TABLE` thủ công).

## 5. Chi tiết các Class và Hàm

### 1. `FacebookDatabase` (Class)
- **Mô tả**: Facade để khởi tạo schema, quản lý bảng, trigger full-text search và kết nối tới các repositories.
- **Thuộc tính**:
  - `_pool`: Connection pool tái sử dụng.
  - `authors`: Instance của `AuthorRepository`.
  - `posts`: Instance của `PostRepository`.
  - `comments`: Instance của `CommentRepository`.
  - `config`: Instance của `ConfigRepository`.

- **Các hàm**:
  - `__init__(self)`: Khởi tạo pool và các repositories, ngay lập tức gọi `_init_schema()` và `_init_tables()`.
  - `_init_schema(self) -> None`: (Private) Gọi pool để đảm bảo schema `facebook` tồn tại.
  - `_init_tables(self) -> None`: (Private) Chạy SQL thô (raw SQL) để tạo các bảng `authors`, `posts`, `comments`, `attachments`, `config`. Tạo các Index thông thường và Index GIN cho tsvector. Định nghĩa luôn Trigger PostgreSQL (bằng PL/pgSQL) để tự động cập nhật search vector khi insert/update dữ liệu.
  - `get_config(self, key: str, default: str = "") -> str`: Đọc giá trị cấu hình theo `key` từ bảng `config`. Trả về chuỗi `default` nếu không có.
  - `set_config(self, key: str, value: str) -> None`: Lưu hoặc ghi đè (upsert) cấu hình `key` = `value` vào bảng `config`.
  - `@property def pool(self)`: Cung cấp quyền truy cập trực tiếp vào đối tượng kết nối `shared_pool` cho các thao tác phức tạp bên ngoài.

### Biến toàn cục: `fb_db`
- Là một instance của `FacebookDatabase()`, dùng như Singleton để các file khác gọi trực tiếp.
