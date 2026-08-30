# Tài liệu: `proxify/plugins/base.py`

## 1. Tóm tắt tổng quan
File `base.py` định nghĩa kiến trúc cơ sở cho tất cả các plugin trong Proxify. Nó chứa abstract class `BasePlugin` mà các plugin khác bắt buộc phải kế thừa để có thể tương tác với các request/response mạng và mở rộng giao diện UI/API của hệ thống.

## 2. Mục đích & Ý nghĩa
- Cung cấp một bộ khung (framework) chuẩn hóa cho việc phát triển các plugin.
- Cho phép các plugin dễ dàng can thiệp vào luồng dữ liệu (intercept) của mitmproxy.
- Hỗ trợ việc khai báo các endpoint API tùy chỉnh và các tab giao diện (UI tabs) trên Dashboard, giúp mở rộng chức năng của Proxify một cách linh hoạt mà không ảnh hưởng tới core.

## 3. Mối liên hệ
- Được import và kế thừa bởi tất cả các plugin khác trong hệ thống (như `facebook.py`, `zalo.py`, `youtube.py`, `tls_spoofer.py`).
- Tương tác trực tiếp với cơ chế proxy của hệ thống thông qua các hàm hook (`on_request`, `on_response`).
- Kết nối với framework web `aiohttp` để đăng ký các API routes và UI.

## 4. Rủi ro (Risks & Edge Cases)
- **Hiệu năng:** Nếu các hàm `on_request` hoặc `on_response` ở các class con xử lý quá chậm hoặc sử dụng blocking IO, toàn bộ proxy sẽ bị nghẽn (do chạy trên event loop bất đồng bộ).
- **Tương thích:** Nếu thư viện mitmproxy nâng cấp và thay đổi cấu trúc của đối tượng `flow`, các hàm hook có thể bị lỗi.

## 5. Chi tiết các Class và Hàm
### Class `BasePlugin(ABC)`
Là lớp trừu tượng đại diện cho một plugin.
- **Thuộc tính:**
  - `name`: Tên của plugin (string).
  - `description`: Mô tả chức năng plugin (string).
  - `version`: Phiên bản (string).
  - `target_domains`: Danh sách (list) các domain mục tiêu. Nếu rỗng, plugin sẽ áp dụng toàn cục (mọi domain).
- **Hàm `__init__(self, storage=None, config=None)`**:
  - Khởi tạo instance plugin.
  - `storage`: Lưu trữ instance dùng để lưu request.
  - `config`: Lưu các tuỳ chỉnh config dưới dạng dict.
  - Khởi tạo logger riêng dựa vào tên class.
- **Hàm `on_request(self, flow: Any) -> None`**:
  - Hook bất đồng bộ, được gọi bởi proxy khi nhận một request. 
  - Mặc định là pass (không làm gì), các class con ghi đè để thay đổi flow hoặc lấy thông tin.
- **Hàm `on_response(self, flow: Any) -> None`**:
  - Hook bất đồng bộ, được gọi bởi proxy khi nhận response từ server.
  - Mặc định là pass, class con ghi đè để chỉnh sửa response (VD: chặn quảng cáo).
- **Hàm `get_api_routes(self) -> List[web.RouteDef]`**:
  - Trả về danh sách route cho aiohttp server của Dashboard. Mặc định rỗng.
- **Hàm `get_ui_tabs(self) -> List[Dict[str, str]]`**:
  - Trả về danh sách cấu hình tab cho Dashboard (định dạng dict chứa id, label, đường dẫn). Mặc định rỗng.
