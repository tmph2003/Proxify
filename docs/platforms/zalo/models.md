# Tài liệu: `proxify/platforms/zalo/models.py`

## 1. Tóm tắt tổng quan
File `models.py` định nghĩa các Data Class (lớp cấu trúc dữ liệu) theo chuẩn mô hình dữ liệu (Data Models) cho ứng dụng phân hệ Zalo. Các lớp này có cấu trúc ánh xạ gần giống hoặc 1-1 với cấu trúc của các bảng PostgreSQL trong schema `zalo`.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Chuẩn hóa kiểu dữ liệu, các thuộc tính mặc định, phục vụ cho việc truyền tải đối tượng (Object Mapping) một cách dễ dàng, thay vì phải làm việc với các Dictionary lộn xộn trong Python.
- **Ý nghĩa**: Đảm bảo an toàn kiểu dữ liệu (Type Safety) và hỗ trợ tự động hoàn thành (Autocomplete/Intellisense) cực tốt cho IDE khi lập trình các module hoặc API trả về cho nền tảng Zalo.

## 3. Mối liên hệ
- Tuy hiện tại các logic CSDL (`repository.py`) có thể ghi thẳng Dict/Biến rời để đẩy vào PostgreSQL, nhưng mô hình DataClass này vẫn rất hữu dụng cho việc hiển thị (Serialize) dữ liệu ra API/Web UI bằng JSON.
- Model này đại diện cho những gì được lấy từ `zalo.groups`, `zalo.users`, `zalo.scan_jobs`.

## 4. Rủi ro (Risks & Edge Cases)
- **Đồng bộ với CSDL**: Thuộc tính của model và các cột SQL có thể lệch pha (out of sync). Nếu thêm bảng hoặc thêm cột bên trong file `database.py` mà quên khai báo bên model thì sẽ mất dữ liệu khi ép kiểu trả về. 
- Không có module ORM (như SQLAlchemy) ràng buộc trực tiếp nên bản chất các model này chỉ là nơi chứa (Containers), chúng không tự động lưu dữ liệu xuống database khi giá trị thuộc tính bị thay đổi.

## 5. Chi tiết các Class và Hàm

Tất cả các mô hình dưới đây đều sử dụng decorator `@dataclass` của thư viện chuẩn Python.

### 1. `ZaloGroup` (Class)
- **Mô tả**: Mô tả thực thể Nhóm (Group) của Zalo.
- **Thuộc tính**:
  - `group_id`: Chuỗi (ID của Group).
  - `display_name`: Tên nhóm.
  - `total_member`: Tổng số thành viên.
  - `avatar`: Link ảnh đại diện.
  - `raw_data`: `dict` lưu trữ các dữ liệu JSON thô chưa xử lý từ Zalo Web. Dùng `field(default_factory=dict)` để đảm bảo mỗi instance khởi tạo một dict độc lập.
  - `created_at` / `updated_at`: Thời gian (datetime) ghi nhận hệ thống.
  - `db_member_count`: Cột tính toán mở rộng sinh ra từ lệnh JOIN CSDL.

### 2. `ZaloUser` (Class)
- **Mô tả**: Mô tả thực thể Thành Viên (User) Zalo.
- **Thuộc tính**:
  - `user_id`: Chuỗi UID chính của user Zalo.
  - `global_id`: Chuỗi globalID (định danh toàn cầu mà Zalo dùng định danh tài khoản xuyên mạng).
  - `display_name`: Tên hiển thị người dùng (Zalo Name).
  - `avatar`: Ảnh đại diện.
  - `phone`: Chuỗi Số điện thoại.
  - `raw_data`: Bộ JSON thô.
  - `created_at` / `updated_at`: Thời điểm theo dõi.

### 3. `ZaloScanJob` (Class)
- **Mô tả**: Mô tả tác vụ cào dữ liệu của Worker (`bot.py`).
- **Thuộc tính**:
  - `id`: Định danh tăng dần trong CSDL.
  - `link`: Chuỗi chứa đường dẫn Zalo (ví dụ `https://zalo.me/g/...` hoặc `group_id:...`).
  - `group_id`: ID sinh ra sau khi bot phân tích URL.
  - `status`: Trạng thái tác vụ (`pending`, `running`, `completed`, `error`).
  - `members_found`: Số lượng thành viên móc được.
  - `error_message`: Cảnh báo lỗi (nếu bot bị hỏng).
  - `created_at`, `started_at`, `completed_at`: Mốc thời gian của từng khâu thực thi.
- **Các hàm**:
  - `to_dict(self) -> dict`: Hàm Serialization hỗ trợ chuyển một đối tượng Dataclass thành một Dictionary nguyên thủy. Nếu thuộc tính có kiểu `datetime`, nó tự động ép thành dạng chuỗi chuẩn `.isoformat()`. Điều này hữu ích để FastAPI có thể render thành JSON mà không gặp lỗi.
