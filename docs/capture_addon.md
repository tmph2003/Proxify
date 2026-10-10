# Tài liệu: `capture_addon.py`

## 1. Tóm tắt tổng quan
File này định nghĩa lớp `CaptureAddon`, một addon của `mitmproxy` chịu trách nhiệm chặn (intercept) tất cả luồng dữ liệu HTTP/HTTPS đi qua proxy. Nó có khả năng lọc bỏ các tệp tĩnh (hình ảnh, CSS, JS) hoặc các domain không cần thiết, sau đó phân phối lưu lượng cho hệ thống plugin và lưu trữ lại qua hệ thống Event Bus.

## 2. Mục đích & Ý nghĩa
- Là trái tim của quá trình phân tích lưu lượng: Nắm bắt các sự kiện `request`, `responseheaders` và `response` từ `mitmproxy`.
- Đảm bảo tính linh hoạt: Nó có cơ chế `_get_matching_plugins` để chỉ chạy các plugin trên những domain chỉ định, và tối ưu hiệu suất bộ nhớ bằng cách dùng luồng (stream) thay vì tải toàn bộ nội dung của các file tĩnh (như ảnh, video) vào RAM.
- Đóng gói dữ liệu và xuất (publish) sự kiện `response_captured` cho các lớp nhận (như luồng lưu trữ CSDL và bảng điều khiển).

## 3. Mối liên hệ
- Hoạt động bên trong vòng đời của `mitmproxy`, được gắn (add) vào addon list từ `server.py`.
- Lắng nghe cấu hình tĩnh `config.json` để lấy bộ quy tắc lọc (Ignore extensions, domains).
- Kích hoạt các plugin thu thập dữ liệu tùy chỉnh (`proxify.plugins.registry.get_all_plugin_classes`).
- Xuất sự kiện cho hệ thống Event Bus (`proxify.core.events.bus`).

## 4. Rủi ro (Risks & Edge Cases)
- **Hiệu năng & Tràn bộ nhớ (OOM):** Mặc dù có cơ chế loại trừ extension, nhưng nếu người dùng tải một file lớn không có đuôi mở rộng hợp lệ, mitmproxy sẽ phải buff toàn bộ payload vào RAM, làm chậm hệ thống hoặc gây tràn bộ nhớ.
- **Thắt cổ chai (Bottleneck):** Việc gọi tất cả các plugin hoạt động tuần tự bên trong các async hook (`request`, `response`) có thể làm tăng độ trễ (latency) của luồng mạng. Nếu một plugin bị treo, toàn bộ request của máy khách cũng bị treo theo.

## 5. Chi tiết các Class và Hàm
- **`load_config()`**: Hàm tiện ích đọc nội dung file cấu hình (nếu tồn tại) `config.json` để xác định danh sách các đuôi file mở rộng và tên miền (domain) bị bỏ qua, giảm tải cho proxy. Trả về cấu hình chuẩn hoặc cấu hình mặc định.
- **Class `CaptureAddon`**: Trình chặn chính của mitmproxy.
  - **`__init__(storage, broadcast_fn, is_db_enabled_fn, domain_filter)`**: Khởi tạo biến lưu trữ, hàm broadcast cho Dashboard, hàm xác định trạng thái kết nối CSDL và tải tất cả plugin từ `registry`. Nó sử dụng `functools.lru_cache` để tối ưu hàm tìm plugin.
  - **`_get_matching_plugins_impl(domain)`**: Tìm và trả về danh sách các plugin có khai báo domain mục tiêu (target_domains) trùng với tên miền của request.
  - **`request(flow: http.HTTPFlow)`**: Hook của mitmproxy. Chạy bất đồng bộ, gửi `flow` qua các plugin. Bỏ qua flow nếu đã có lỗi hoặc đã bị khối (ad_blocked).
  - **`responseheaders(flow: http.HTTPFlow)`**: Hook kích hoạt sau khi nhận được HTTP Header từ server nhưng chưa nhận phần thân (body). Hàm này kiểm tra phần mở rộng (ví dụ `.mp4`, `.zip`) để thiết lập `flow.response.stream = True`, giúp tiết kiệm RAM và không cache body vào bộ nhớ proxy.
  - **`response(flow: http.HTTPFlow)`**: Hook gọi sau khi một request kết thúc hoàn chỉnh. Gọi tiếp plugin để trích xuất dữ liệu, kiểm tra các điều kiện lưu vào cơ sở dữ liệu (`db_allowed_domains`) và cuối cùng đưa tín hiệu `response_captured` ra hệ thống event bus.
  - **`error(flow: http.HTTPFlow)`**: Hook bắt lỗi mạng. Nếu lỗi xảy ra do chủ động ngắt (như cơ chế chặn quảng cáo), sẽ không xuất log, tránh làm bẩn console. Ngược lại sẽ ghi lại lỗi (ví dụ không kết nối được đến server đích).
