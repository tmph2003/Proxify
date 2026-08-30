# Tài liệu: `proxify/plugins/__init__.py`

## 1. Tóm tắt tổng quan
File `__init__.py` là file khởi tạo cho package `proxify.plugins`, giúp đóng gói thư mục này thành một module Python hợp lệ và quản lý các thành phần công khai (public exports).

## 2. Mục đích & Ý nghĩa
- Gắn kết thư mục `plugins` thành một Python package.
- Cung cấp một namespace gọn gàng. Người dùng hệ thống có thể import trực tiếp từ `proxify.plugins` (ví dụ: `from proxify.plugins import register_plugin`) thay vì phải trỏ tới từng file con (như `proxify.plugins.registry`).

## 3. Mối liên hệ
- Import các class và hàm từ `base.py` và `registry.py`.
- Được sử dụng bởi core của Proxify hoặc các thư viện khác bên ngoài khi muốn tương tác với hệ thống plugin.

## 4. Rủi ro (Risks & Edge Cases)
- **Vòng lặp import (Circular Import):** Nếu không cẩn thận khi import lẫn nhau giữa các module bên trong package và bên ngoài gọi vào, có thể gây lỗi circular dependency.
- Các plugin thật sự (như `facebook`, `youtube`) không được export trực tiếp tại đây, nhằm tránh import thừa hoặc gây chậm quá trình khởi động.

## 5. Chi tiết các Class và Hàm
File này không chứa định nghĩa class hay hàm riêng biệt nào, mà chỉ thực hiện việc import và định nghĩa `__all__`:
- **Danh sách `__all__`**: Định nghĩa các thành phần được export ra ngoài khi dùng `from proxify.plugins import *`. Bao gồm:
  - `BasePlugin`: Class cơ sở cho các plugin.
  - `register_plugin`: Decorator đăng ký plugin.
  - `discover_plugins`: Hàm nạp plugin tự động.
  - `get_all_plugin_classes`: Hàm lấy danh sách plugin hiện có.
