# Tài liệu: `dashboard.py`

## 1. Tóm tắt tổng quan
File `dashboard.py` định nghĩa lớp `Dashboard`, chịu trách nhiệm chạy một máy chủ web nội bộ bằng framework `aiohttp`. Nó cung cấp giao diện hiển thị cho người dùng và một loạt các API RESTful cùng với WebSocket để giao tiếp theo thời gian thực (real-time).

## 2. Mục đích & Ý nghĩa
- Cung cấp giao diện trực quan cho người dùng theo dõi các HTTP request và response đang được bắt bởi hệ thống proxy.
- Đóng vai trò là một Backend Server quản lý các thao tác từ UI như: lọc request, xem chi tiết request, thống kê lưu lượng, bật/tắt lưu trữ dữ liệu (Database), tải cấu hình và xuất dữ liệu ra nhiều định dạng.
- Hỗ trợ cơ chế Broadcast (phát thanh) sự kiện mới nhất cho tất cả các web client kết nối qua WebSocket một cách nhanh chóng.

## 3. Mối liên hệ
- Khởi tạo và liên kết bởi `server.py` để chạy trên luồng chính của ứng dụng.
- Truy vấn, đọc và xoá dữ liệu từ `proxify.storage.RequestStorage`.
- Sử dụng các hàm xuất dữ liệu từ `proxify.exporter` (JSON, HAR, Python, cURL).
- Động học đăng ký các route API (API Routes) và các thành phần giao diện (UI Tabs) được cung cấp bởi các Plugin (`proxify.plugins.registry`).
- Có liên kết với `proxify.utils.stealth` để kiểm tra độ bảo mật/ẩn danh (Stealth verify) qua API.

## 4. Rủi ro (Risks & Edge Cases)
- **Rò rỉ tài nguyên (Resource Leak):** Cần đảm bảo các kết nối WebSocket được đóng và loại bỏ khỏi `self.ws_clients` khi xảy ra lỗi mạng; nếu không, có thể gây quá tải bộ nhớ và treo ứng dụng (Dead connections).
- **Lỗ hổng bảo mật:** Máy chủ Dashboard không có cơ chế xác thực (Authentication). Nếu nó được lắng nghe trên `0.0.0.0` thay vì `127.0.0.1`, bất kỳ ai trong mạng LAN/Internet đều có thể xem toàn bộ lưu lượng hoặc cấu hình proxy, tạo ra lỗ hổng rò rỉ dữ liệu nhạy cảm.
- **Xử lý bất đồng bộ:** Cơ chế broadcast dùng chuỗi JSON với hàm `default=str` có thể sụp đổ (crash loop) nếu dữ liệu gửi đi chứa object không thể mã hóa JSON.

## 5. Chi tiết các Class và Hàm
- **Class `Dashboard`**: Quản lý vòng đời và các endpoints của giao diện web.
  - **`__init__(storage, host, port)`**: Khởi tạo cấu hình mạng (`host`, `port`), đối tượng lưu trữ (`storage`), tập các websocket đang sống (`ws_clients`) và đối tượng Ứng dụng `web.Application()`. Sau đó gọi `_setup_routes()`.
  - **`_setup_routes()`**: Khai báo danh sách các endpoints GET/POST/DELETE (như `/api/requests`, `/ws`, `/api/stats`, v.v.). Hàm này còn nạp tự động giao diện và API từ tất cả plugin đang có.
  - **`_handle_toggle_db(request)`**: Xử lý API cập nhật tuỳ chọn có ghi vào CSDL hay không và danh sách domain được lưu.
  - **`_handle_get_config(request)`**: Trả về thông số thiết lập CSDL hiện hành cho Frontend.
  - **`broadcast(data, msg_type)`**: Lặp qua tất cả websocket, đẩy thông điệp theo format JSON. Đồng thời làm sạch/xoá bỏ các kết nối websocket đã chết (ConnectionError).
  - **`_handle_style_css(request)`** / **`_handle_index(request)`**: Render các file tĩnh (`style.css` và `index.html`) hỗ trợ UI.
  - **`_handle_websocket(request)`**: Định nghĩa và duy trì vòng đời kết nối WebSocket (`ws`) cho mỗi client. Chặn tin nhắn đến từ client nếu có xử lý và theo dõi lỗi.
  - **`_get_start_of_today_epoch()`**: Hàm tiện ích lấy thời gian Unix timestamp bắt đầu từ 00:00 của ngày hiện hành, hỗ trợ bộ lọc dữ liệu nhanh trên Dashboard.
  - **`_handle_list_requests(request)`**: Lấy dữ liệu danh sách requests từ bảng (có hỗ trợ filter: domain, status code, graphql).
  - **`_handle_get_request(request)`**: Lấy chi tiết toàn bộ Header/Body của 1 request duy nhất theo ID.
  - **`_handle_get_domains(request)`**: Đếm và thống kê số lượng request theo Domain.
  - **`_handle_get_stats(request)`**: Lấy thông tin tóm tắt lưu lượng (tổng request, thành công, lỗi, tổng kích thước) từ lưu trữ.
  - **`_handle_export(request)`**: Chuyển hướng xuất file tuỳ theo format truyền lên (JSON, HAR, PYTHON, CURL) dựa trên tập request được chọn.
  - **`_handle_delete_requests(request)`**: Xoá (có chọn lọc qua ID) các bản ghi để giải phóng ổ cứng.
  - **`_handle_stealth_verify(request)`** / **`_handle_stealth_stats(request)`**: Kiểm tra Fingerprint TLS hiện hành bằng StealthSessionManager và xem thông số của trình giả lập.
  - **`get_app()`**: Hàm trả về đối tượng aiohttp app cho server runner.
