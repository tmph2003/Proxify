# Tài liệu: `proxify/platforms/zalo/database.py`

## 1. Tóm tắt tổng quan
File `database.py` hoạt động dưới dạng Facade Pattern (Mặt tiền) quản lý chung hệ thống cơ sở dữ liệu cho phần thu thập thông tin của Zalo. Khởi tạo một đối tượng kết nối trỏ tới schema `zalo` trong PostgreSQL. Tự động kiểm tra và tạo ra cấu trúc bảng (schema) ngay khi ứng dụng chạy.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Chuẩn hóa, tự động hoá việc thiết lập CSDL cho mô đun Zalo, cung cấp bộ truy xuất tập trung để gọi đến các Repository cụ thể.
- **Ý nghĩa**: Bất kỳ hàm bóc tách dữ liệu hay Crawler nào của Zalo cũng chỉ cần gọi thông qua biến `zalo_db` mà không cần biết cách kết nối tới PostgreSQL hay cách các câu lệnh SQL INSERT hoạt động. Việc tự tạo bảng giúp người cài đặt ban đầu (hoặc chạy docker) không phải quan tâm tới việc Import dữ liệu Migration.

## 3. Mối liên hệ
- Nó sử dụng kết nối chia sẻ chung `shared_pool` từ `proxify.database`.
- Khởi tạo và nắm giữ 5 thực thể Repository đến từ file `zalo/repository.py`: `GroupRepository`, `UserRepository`, `MembershipRepository`, `ScanJobRepository`, `StatsRepository`.

## 4. Rủi ro (Risks & Edge Cases)
- **Hardcoded Schema (Sơ đồ cứng)**: Giống bên Facebook, cấu trúc bảng Zalo được gán cứng qua lệnh `CREATE TABLE IF NOT EXISTS`. Bất kỳ thay đổi cấu trúc bảng nào trong tương lai (thêm cột, sửa kiểu dữ liệu) sẽ không tự động cập nhật được, dẫn đến lỗi crash nếu ứng dụng mới đòi hỏi cột mà DB hiện hành không có.
- Không có bất kỳ trigger nào được tự động hóa. Việc duy trì tính toàn vẹn phụ thuộc 100% vào code Repository.

## 5. Chi tiết các Class và Hàm

### 1. `ZaloDatabase` (Class)
- **Mô tả**: Facade để khởi tạo schema, quản lý các bảng và kết nối tới các repositories của hệ thống Zalo.
- **Thuộc tính**:
  - `_pool`: Tái sử dụng Database pool của Proxify.
  - `groups`: Đối tượng `GroupRepository`.
  - `users`: Đối tượng `UserRepository`.
  - `memberships`: Đối tượng `MembershipRepository`.
  - `jobs`: Đối tượng `ScanJobRepository`.
  - `_stats`: Đối tượng `StatsRepository`.

- **Các hàm**:
  - `__init__(self)`: Gắn kết các biến instance và ngay lập tức chạy `_init_schema()`, `_init_tables()`.
  - `_init_schema(self) -> None`: (Private) Gọi pool để tạo schema `zalo`.
  - `_init_tables(self) -> None`: (Private) Dùng raw SQL tạo 4 bảng chính:
    - `zalo.groups`: Lưu nhóm (ID, tên, lượt member, avatar, JSON gốc).
    - `zalo.users`: Lưu thành viên (ID, số ĐT, global ID, JSON gốc).
    - `zalo.group_members`: Bảng liên kết trung gian N-N lưu thời gian tham gia nhóm. Tạo index cho `group_id` và `user_id`.
    - `zalo.scan_jobs`: Bảng đợi chứa link nhóm Zalo để Bot lấy chạy ngầm.
  - `get_stats(self) -> dict`: Phương thức lối tắt (shortcut) gọi xuyên qua `self._stats.get_stats()` để lấy số liệu thống kê.
  - `@property def pool(self)`: Cung cấp quyền truy cập tới đối tượng kết nối `shared_pool` cho các thao tác phức tạp khác từ bên ngoài.
