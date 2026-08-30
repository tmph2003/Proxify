# Tài liệu: `proxify/platforms/facebook/database.py`

## 1. Tóm tắt tổng quan
File `database.py` đóng vai trò là một Facade (mặt tiền) để quản lý toàn bộ các thao tác cơ sở dữ liệu (Database) liên quan đến nền tảng Facebook. Nó chịu trách nhiệm tự động khởi tạo schema (`facebook`) và các bảng (tables) cần thiết khi được import, đồng thời tạo ra một điểm truy cập duy nhất (singleton-like instance) `fb_db` tới các lớp Repository tương ứng.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Tự động hóa quá trình thiết lập CSDL, tạo bảng, các chỉ mục (index) tăng tốc tìm kiếm và search_vector cho Full-text Search. Gom nhóm các Repository (Authors, Posts, Comments, Config) vào chung một class để dễ dàng gọi.
- **Ý nghĩa**: Giúp mã nguồn quản lý CSDL trở nên tập trung, gọn gàng. Bất cứ mô-đun nào cần thao tác với DB Facebook chỉ cần import đối tượng `fb_db` từ file này. Đảm bảo tính toàn vẹn của cấu trúc CSDL mà không cần chạy file migration bằng tay.

## 3. Mối liên hệ
- Nó phụ thuộc vào `shared_pool` từ `proxify.database` để lấy kết nối PostgreSQL.
- Gọi trực tiếp đến `AuthorRepository`, `PostRepository`, `CommentRepository`, `ConfigRepository` từ file `repository.py`.
- Đối tượng `fb_db` sinh ra ở cuối file này được import bởi các crawler, extractor để lưu dữ liệu và đọc cấu hình (cookie, cursor).

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
