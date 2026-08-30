# Tài liệu: `proxify/platforms/zalo/repository.py`

## 1. Tóm tắt tổng quan
File `repository.py` triển khai mẫu thiết kế Repository Pattern để đảm nhiệm việc truy vấn, chèn và trích xuất dữ liệu trên schema `zalo` của cơ sở dữ liệu PostgreSQL. Bao gồm 5 repositories quản lý 4 bảng chính: Nhóm (Groups), Người dùng (Users), Thành viên Nhóm (Group Members), Hàng đợi quét (Scan Jobs) và Thống kê.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Đảm bảo tất cả các câu lệnh SQL liên quan đến phân hệ Zalo được lưu giữ ở một nơi, cô lập các thao tác cấp thấp (low-level database interactions) khỏi mã nghiệp vụ.
- **Ý nghĩa**: Tính năng Upsert (`ON CONFLICT DO UPDATE`) được ứng dụng dày đặc để liên tục làm mới dữ liệu người dùng/nhóm mỗi khi Zalo Proxy bắt được tín hiệu JSON mà không gây trùng lặp (Duplicate) bản ghi.

## 3. Mối liên hệ
- Nó được import bởi `database.py` của zalo để ghép thành facade `zalo_db`.
- Hàm Upsert được gọi trực tiếp bởi tiến trình Proxy Hook (`handle_capture_dump`) trong module `extractor.py` mỗi khi có dữ liệu trả về từ trình duyệt.
- API RESTful Backend (ví dụ cho UI bảng điều khiển) có thể dùng hàm `get_all`, `get_members`, `export_members_csv` trong này để trả dữ liệu ra ngoài.

## 4. Rủi ro (Risks & Edge Cases)
- **Truy vấn M-N quá chậm**: Lệnh `get_members` dùng phép kết (JOIN) giữa bảng `group_members` và bảng `users`. Nếu bảng `users` chứa đến hàng triệu bản ghi và việc tìm kiếm (ILIKE) chứa chuỗi `%` hai chiều thì PostgreSQL sẽ không dùng index được (Full Table Scan), gây nghẽn cổ chai CPU rất nặng.
- **Dữ liệu CSV tràn/lỗi định dạng**: Hàm `export_members_csv` dùng phép nối chuỗi tĩnh để sinh file CSV. Nếu tên hiển thị của người dùng (display_name) có chứa dấu nháy kép `"` hoặc xuống dòng (newline) dù đã cố lọc dấu phẩy `,`, vẫn có thể phá vỡ định dạng CSV tiêu chuẩn.
- **Lỗi Injection/SQL param**: Dù dùng param `%s` chuẩn psycopg2 giúp chống SQL Injection, nhưng các khối `ILIKE %s` tạo chuỗi `%search%` bằng tay đôi khi cần làm cẩn thận để tránh lỗi với các kí tự đặc biệt (VD: `%` hay `_`).

## 5. Chi tiết các Class và Hàm

### 1. `GroupRepository` (Class)
- **Mô tả**: Lưu trữ & truy vấn bảng `zalo.groups`.
- **Các hàm**:
  - `upsert(group_id, display_name, total_member, raw_data)`: Chèn/cập nhật nhóm, dùng hàm `GREATEST` giữ lại số lượng member cao nhất. Dữ liệu thô `raw_data` được gói qua `psycopg2.extras.Json` để an toàn.
  - `get_all(search, limit, offset) -> list[dict]`: Truy vấn danh sách Group, kết hợp (LEFT JOIN) với `group_members` để đếm số lượng thực tế đã thu thập `db_member_count`. Có hỗ trợ tìm kiếm tên theo `ILIKE`.
  - `get_members(group_id, search, limit, offset) -> list[dict]`: Truy xuất mọi thành viên có liên kết trung gian thuộc về `group_id`, trả về thông tin `user_id`, `global_id`, `phone`, v.v...
  - `export_members_csv(group_id) -> str`: Gom hàng loạt data của một group và ép thành một chuỗi CSV lớn.

### 2. `UserRepository` (Class)
- **Mô tả**: Lưu trữ bảng `zalo.users`.
- **Các hàm**:
  - `upsert(user_id, global_id, display_name, avatar, phone, raw_data)`: Tương tự Group, nhưng sử dụng hàm `COALESCE(NULLIF...` để tránh việc vô tình ghi đè bằng một chuỗi rỗng (`""`) lên dữ liệu số điện thoại hay tên thực tế đã từng thu thập tốt.
  - `get_all(search, limit, offset)`: Truy vấn danh sách toàn bộ Users trên hệ thống, phân trang.

### 3. `MembershipRepository` (Class)
- **Mô tả**: Lưu trữ bảng `zalo.group_members`.
- **Các hàm**:
  - `link_members(group_id, user_ids: list)`: Liên kết N-N. Chạy vòng lặp INSERT vào bảng. Khối lượng được an toàn vì có khoá chính và điều kiện `ON CONFLICT DO NOTHING`.

### 4. `ScanJobRepository` (Class)
- **Mô tả**: Lưu trữ bảng `zalo.scan_jobs`, phục vụ cho Zalo Bot.
- **Các hàm**:
  - `create(link) -> Optional[int]`: Đẩy URL của nhóm mới vào queue DB (cột status mặc định là `pending`). `RETURNING id` trả về ID tác vụ vừa sinh.
  - `update(job_id, **kwargs)`: Cập nhật động trạng thái qua **kwargs dictionary. Hỗ trợ truyền đặc tả `CURRENT_TIMESTAMP` để cập nhật cột datetime.
  - `get_all(limit)`: Liệt kê các lệnh đã quét để theo dõi (Monitor).
  - `get_pending()`: Hàm dùng cho con Bot đọc vòng lặp để lấy task `pending`.
  - `get_running_jobs()`: Truy xuất tác vụ đang kẹt trạng thái `running`.

### 5. `StatsRepository` (Class)
- **Mô tả**: Thống kê cho bảng tổng quát trang chủ.
- **Các hàm**:
  - `get_stats() -> dict`: Chạy 4 lệnh `COUNT(*)` đếm tổng lượng users, groups, members, scan jobs trong DB rồi trả về Dictionary báo cáo.
