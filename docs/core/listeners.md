# Tài liệu: listeners.py

## 1. Tóm tắt tổng quan
Module `listeners.py` chứa các cài đặt cụ thể xử lý sự kiện gói tin HTTP (flow) của proxy, nổi bật gồm hai luồng chính là phát sóng tóm tắt gói tin ra Dashboard và ghi dữ liệu chi tiết vào cơ sở dữ liệu.

## 2. Mục đích & Ý nghĩa
Tách bạch logic xử lý các HTTP flow ra khỏi nhân (core) của mitmproxy. 
- `DashboardBroadcaster` đảm nhận gửi dữ liệu cực kỳ nhẹ (metadata) đến UI theo thời gian thực.
- `DatabaseWriter` giúp trích xuất và định dạng toàn bộ chi tiết của request/response để lưu trữ lâu dài.

## 3. Mối liên hệ
- Nhận input là các gói tin `http.HTTPFlow` từ mitmproxy.
- Kế thừa giao thức `EventListener` từ `proxify.core.interfaces`.
- Sử dụng hàm tiện ích từ `proxify.utils.content` để kiểm tra định dạng chữ và giới hạn size.
- Phối hợp với `proxify.core.events.bus` để kích hoạt sự kiện `db_row_created` sau khi ghi database.

## 4. Rủi ro (Risks & Edge Cases)
- **Overhead bộ nhớ:** `DatabaseWriter` lưu lại toàn bộ body của request và response (đã khống chế bằng `MAX_RESPONSE_SIZE`). Ở điều kiện lưu lượng (traffic) quá cao, việc parse và đẩy vào DB có thể làm tốn dung lượng RAM và gây lag.
- **Lỗi giải mã chuỗi (Encoding):** Dù đã bắt lỗi `ValueError` khi parse text từ body, vẫn có rủi ro định dạng chuỗi dị thường bị lỗi hiển thị. 
- **Ký tự Null (`\x00`):** File có xử lý lược bỏ ký tự `\x00` (nguyên nhân gây lỗi INSERT db) khỏi text. Việc này có thể làm thay đổi nội dung nguyên bản nếu body chứa binary trá hình text.

## 5. Chi tiết các Class và Hàm

- **`Class DashboardBroadcaster(EventListener)`**: Thành phần chịu trách nhiệm phát dữ liệu tóm lược cho frontend.
  - **`__init__(self, broadcast_fn: Callable)`**: Khởi tạo với một hàm `broadcast_fn` (hàm gọi lại để phát dữ liệu qua websocket/bus).
  - **`__call__(self, flow: http.HTTPFlow, db_save: bool, **kwargs)`**: Phân tích request và response hiện tại. Trích xuất thời gian xử lý (`duration_ms`), trạng thái, dung lượng trả về và đường dẫn (xem có phải GraphQL không). Sau đó gói thành dictionary `summary` rồi gửi đi thông qua `broadcast_fn`. Luôn được bọc bằng `try-except` để tránh làm ảnh hưởng quá trình proxy.

- **`Class DatabaseWriter(EventListener)`**: Thành phần chịu trách nhiệm lưu toàn bộ chi tiết HTTP flow.
  - **`__init__(self, storage)`**: Nhận vào đối tượng `storage` (giao diện với DB) để lưu trữ.
  - **`__call__(self, flow: http.HTTPFlow, db_save: bool, **kwargs)`**: 
    - Nếu cờ `db_save` là False thì bỏ qua.
    - Parse toàn bộ thông tin chi tiết: URL đầy đủ, Header, Content-Type, query string...
    - Kiểm tra body theo cờ `MAX_RESPONSE_SIZE`. Nếu là dữ liệu text, lấy đoạn chữ. Nếu binary, hiển thị tag báo hiệu độ dài.
    - Replace ký tự null `\x00` ra khỏi dữ liệu string.
    - Cấu trúc lại bộ dữ liệu vào `data`.
    - Định nghĩa hàm callback `_on_saved(row_id: int)` chạy sau khi db lưu xong. Hàm này ghi log và phát sự kiện `db_row_created` qua `bus`.
    - Gọi luồng lưu dữ liệu bất đồng bộ `self.storage.save_request_async` kèm callback.
