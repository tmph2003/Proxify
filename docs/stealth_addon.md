# Tài liệu: `stealth_addon.py`

## 1. Tóm tắt tổng quan
File `stealth_addon.py` chứa addon `StealthUpstreamAddon` cho `mitmproxy`. Addon này chặn các yêu cầu gửi đi và thay vì để mitmproxy gửi chúng như thông thường, nó sử dụng thư viện `curl_cffi` để thực hiện yêu cầu đóng giả làm trình duyệt (TLS impersonation).

## 2. Mục đích & Ý nghĩa
- Mục đích chính là giả mạo (spoof) dấu vân tay TLS (TLS Fingerprint, JA3) của các trình duyệt phổ biến như Google Chrome, nhằm qua mặt các hệ thống phát hiện bot và tường lửa ứng dụng (WAF) khắt khe (ví dụ: Cloudflare, Akamai).
- Giúp người dùng thu thập hoặc kiểm thử dữ liệu từ những trang web yêu cầu kiểm tra trình duyệt thực tế, điều mà kết nối proxy thông thường của mitmproxy (bằng thư viện Python mặc định) sẽ dễ dàng bị chặn (HTTP 403 / HTTP 503).

## 3. Mối liên hệ
- Đây là một Addon của `mitmproxy`, được đăng ký tại `server.py` khi người dùng bật cờ (flag) `--stealth`.
- Phụ thuộc sâu vào `proxify.utils.stealth.StealthSessionManager` để thiết lập kết nối curl_cffi.
- Bỏ qua việc can thiệp (bypass) đối với các request mang dấu hiệu `x-proxify-crawler` do hệ thống crawler nội bộ tự thực hiện TLS spoofing, tránh hiện tượng giả mạo hai lần (double spoofing).

## 4. Rủi ro (Risks & Edge Cases)
- **Mất tính năng WebSocket:** Công cụ `curl_cffi` chủ yếu phục vụ yêu cầu HTTP/HTTPS truyền thống, việc sử dụng nó có thể làm phá vỡ hoặc không hỗ trợ cơ chế nâng cấp kết nối WebSocket. (Code hiện tại có bọc điều kiện bỏ qua WebSocket).
- **Hiệu năng & Tài nguyên:** Sử dụng một công cụ ngoài (curl_cffi) dưới nền sẽ làm tăng độ trễ mạng (latency) cho mỗi yêu cầu và có thể tốn bộ nhớ hơn.
- **Mất / Lỗi Headers đặc thù:** Phải thực hiện tái tạo HTTP Headers một cách thủ công giữa định dạng của mitmproxy và curl_cffi. Nếu có các Hop-by-hop headers bị xử lý sai, server đích có thể ngắt kết nối.

## 5. Chi tiết các Class và Hàm
- **Class `StealthUpstreamAddon`**: Một addon mitmproxy đứng ở khâu cuối cùng trước khi gửi lên upstream.
  - **`__init__(target_domains=None)`**: Khởi tạo biến bộ lọc tên miền và đối tượng quản lý session giả mạo `StealthSessionManager()`.
  - **`request(flow: http.HTTPFlow)`**: Bắt luồng request ở mitmproxy. Hàm này sẽ:
    1. Kiểm tra và bỏ qua những request nâng cấp websocket hoặc đến từ chính trình thu thập dữ liệu gốc (`x-proxify-crawler`).
    2. Bỏ qua nếu domain không nằm trong danh sách mục tiêu.
    3. Đẩy thông tin method, header, body cho `_manager.request(...)` chạy qua `curl_cffi`.
    4. Xây dựng lại `flow.response` giả lập (mocked HTTP Response) từ kết quả lấy về, chú ý lọc bỏ các header "hop-by-hop" (content-encoding, transfer-encoding) để mitmproxy tiếp tục quá trình đẩy dữ liệu về client một cách trơn tru.
    5. Xử lý các lỗi HTTP `StealthRequestError` và ngoại lệ chung để bọc thành mã lỗi Gateway 502, ngăn ứng dụng bị văng (crash).
