# Tài liệu: `__init__.py`

## 1. Tóm tắt tổng quan
Module khởi tạo cho package `database`. Đóng vai trò là entry point để các thành phần khác trong dự án có thể dễ dàng lấy được kết nối tới cơ sở dữ liệu.

## 2. Mục đích & Ý nghĩa
Cung cấp một connection pool dùng chung (singleton) duy nhất tên là `pool` cho toàn bộ ứng dụng. Việc dùng chung này giúp tối ưu tài nguyên mạng và máy chủ cơ sở dữ liệu, đồng thời đơn giản hóa cú pháp khi cần tương tác với Database từ bất kỳ platform nào (như Zalo, Facebook,...).

## 3. Mối liên hệ
- **Import từ:** Sử dụng lớp `DatabasePool` được định nghĩa trong file `connection.py` cùng thư mục.
- **Được dùng bởi:** Bất kỳ module nào cần thao tác với cơ sở dữ liệu đều sẽ import biến `pool` từ module này (`from proxify.database import pool`).

## 4. Rủi ro (Risks & Edge Cases)
- Đây là một singleton được khởi tạo ngay khi package được import. Nếu biến môi trường hoặc cấu hình cơ sở dữ liệu sai, các module lấy `pool` sẽ không thể thực thi được bất cứ câu truy vấn nào.

## 5. Chi tiết các Class và Hàm
- **Biến (Khởi tạo):**
  - `pool`: Đây là một object thuộc lớp `DatabasePool`, hoạt động như một singleton (thể hiện duy nhất). Nó quản lý chung các kết nối PostgreSQL thông qua `ThreadedConnectionPool`. Bất cứ truy xuất nào đến DB trong ứng dụng đều sẽ đi qua biến này.
  - `__all__`: Giới hạn các đối tượng được export ra ngoài gồm `pool` và class `DatabasePool`.
