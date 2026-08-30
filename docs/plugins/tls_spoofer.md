# Tài liệu: `proxify/plugins/tls_spoofer.py`

## 1. Tóm tắt tổng quan
File `tls_spoofer.py` là một plugin đánh lừa (spoofing) dấu vân tay TLS (JA3 Bypass). Nó chuyển tiếp các request từ mitmproxy thông qua một HTTP Client hỗ trợ nguỵ trang (giả lập giống Chrome) để qua mặt các hệ thống chống bot như Cloudflare.

## 2. Mục đích & Ý nghĩa
- Cải thiện tỉ lệ thành công khi crawl hoặc gọi API đến các dịch vụ bảo mật cao (như TikTok).
- Sử dụng cơ chế Stealth Engine của hệ thống để mạo danh Client Hello TLS của Chrome.
- Là thành phần quan trọng trong kiến trúc vượt rào chặn bot (bypass anti-bot).

## 3. Mối liên hệ
- Kế thừa `BasePlugin` từ `base.py` và đăng ký bằng `@register_plugin("tls_spoofer")`.
- Sử dụng `StealthSessionManager` từ `proxify.utils.stealth` để thực hiện các request ngầm.
- Tương tác với đối tượng `http.HTTPFlow` của mitmproxy để huỷ request ban đầu và thay thế bằng kết quả giả mạo.

## 4. Rủi ro (Risks & Edge Cases)
- **Hiệu năng & Độ trễ:** Việc tạo request thông qua Curl/CFFI thay vì socket trực tiếp có thể gây tăng độ trễ (latency).
- **Lỗi cấu hình Headers:** Không thể hoàn nguyên một số Header liên quan đến kết nối (như `Transfer-Encoding`), nếu có server nào thực sự yêu cầu nó, request sẽ bị lỗi.
- **Bất đồng bộ:** Nếu `StealthSessionManager` bị quá tải số lượng connection, nó có thể ảnh hưởng tài nguyên chung.

## 5. Chi tiết các Class và Hàm
### Class `TLSSpooferPlugin(BasePlugin)`
Đảm nhiệm vai trò mạo danh TLS cho các domain cấu hình sẵn.
- **Hàm `__init__(self, storage=None, config=None)`**:
  - Lấy danh sách domain mục tiêu từ biến môi trường `SPOOF_DOMAINS` (mặc định là các domain của TikTok).
  - Khởi tạo instance của `StealthSessionManager`.
- **Hàm `on_request(self, flow: Any) -> None`**:
  - Xử lý bất đồng bộ, kiểm tra xem request có trỏ tới các domain mục tiêu hay không.
  - Bỏ qua các loại request như WebSocket hoặc các request do crawler cục bộ (x-proxify-crawler) thực hiện.
  - Sử dụng `StealthSessionManager` để tái thực hiện lại toàn bộ request (method, URL, headers, content).
  - Sau khi lấy được response ngầm, tạo một mitmproxy `Response` thay thế vào `flow.response`, từ đó bỏ qua việc mitmproxy tự kết nối đến server gốc. Xử lý xóa bỏ các header gây lỗi `content-encoding`, `content-length`, `transfer-encoding`.
  - Có cơ chế try/except đón lõng `StealthRequestError` và trả về mã lỗi 502 an toàn.
- **Hàm `shutdown(self)`**:
  - Đóng và giải phóng tài nguyên của `StealthSessionManager` khi tắt plugin.
