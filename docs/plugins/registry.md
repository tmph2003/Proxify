# Tài liệu: `proxify/plugins/registry.py`

## 1. Tóm tắt tổng quan
File `registry.py` cung cấp cơ chế đăng ký và tự động khám phá (discover) các plugin trong thư mục `proxify/plugins/`. Nó duy trì một registry (từ điển) tập trung để lưu trữ tất cả các class plugin khả dụng.

## 2. Mục đích & Ý nghĩa
- Cung cấp cơ chế cắm-và-chạy (plug-and-play). Các plugin mới chỉ cần thêm file vào thư mục và khai báo decorator, không cần sửa đổi mã nguồn cốt lõi để gọi chúng.
- Tự động hóa quá trình nạp (import) các file plugin vào hệ thống.
- Xác thực xem các plugin được đăng ký có kế thừa đúng chuẩn `BasePlugin` hay không.

## 3. Mối liên hệ
- Phụ thuộc vào class `BasePlugin` từ `base.py` để làm chuẩn kiểm tra.
- Sẽ được hệ thống proxy core gọi hàm `discover_plugins()` lúc khởi động.
- Mọi plugin file (như `youtube.py`, `facebook.py`) đều import decorator `register_plugin` từ file này.

## 4. Rủi ro (Risks & Edge Cases)
- **Lỗi import:** Nếu một file plugin chứa mã lỗi (syntax error hoặc lỗi import thư viện ngoài), hàm khám phá sẽ bắt ngoại lệ, ghi log và bỏ qua plugin đó. Người dùng có thể không nhận ra plugin chưa được nạp.
- **Xung đột khóa (Key collision):** Nếu hai plugin dùng chung tham số `name` khi gọi `@register_plugin`, plugin nạp sau sẽ ghi đè plugin trước trong từ điển `_PLUGIN_REGISTRY`.

## 5. Chi tiết các Class và Hàm
- **Biến `_PLUGIN_REGISTRY`**: Kiểu `Dict[str, Type[BasePlugin]]`, nơi lưu các lớp plugin.
- **Hàm `register_plugin(name: str)`**:
  - Là decorator dùng để gắn vào class của các plugin.
  - Kiểm tra xem class truyền vào có kế thừa `BasePlugin` hay không. Nếu không, ném ra lỗi `TypeError`.
  - Thêm class vào `_PLUGIN_REGISTRY` với key là `name`.
- **Hàm `get_all_plugin_classes() -> Dict[str, Type[BasePlugin]]`**:
  - Trả về bản sao của từ điển `_PLUGIN_REGISTRY` cho phép hệ thống bên ngoài lấy danh sách các plugin đã đăng ký.
- **Hàm `discover_plugins() -> None`**:
  - Sử dụng module `pkgutil` để quét qua tất cả các module nằm trong package `proxify.plugins`.
  - Bỏ qua chính nó (`registry`) và file `base`.
  - Tự động gọi `importlib.import_module` cho từng module tìm thấy, từ đó kích hoạt các decorator. Xử lý ngoại lệ an toàn nếu import thất bại và log lại lỗi.
