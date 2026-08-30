# Tài liệu: stealth.py

## 1. Tóm tắt tổng quan
Unified Stealth Engine - Module mạng trọng tâm của Proxify cung cấp giải pháp vượt qua các lớp bảo vệ chống bot (Anti-bot-detection). Xử lý việc làm giả TLS fingerprint, quản lý sự đồng nhất của HTTP header, khởi tạo phiên làm việc mượt mà và tự động nhận diện chặn mềm (soft-block).

## 2. Mục đích & Ý nghĩa
Giúp Proxify mô phỏng lại các trình duyệt thật (như Chrome bản mới nhất) khi cào dữ liệu hoặc tương tác API. Bằng cách sử dụng thư viện `curl_cffi`, engine này ngụy trang TLS handshake, đồng thời tự động quản lý lỗi mạng, giới hạn request (rate limit) bằng chiến lược retry kết hợp backoff (chờ đợi theo hàm mũ) để tránh việc bị phát hiện là tool tự động.

## 3. Mối liên hệ
Đây là lớp giao tiếp mạng (Networking Layer) nền tảng. Tất cả các luồng call API ra bên ngoài (đến Cloudflare, Facebook...) thay vì dùng thư viện `requests` hay `httpx` thông thường sẽ phải đi qua đối tượng `StealthSessionManager` của module này.

## 4. Rủi ro (Risks & Edge Cases)
- **Phụ thuộc thư viện lõi:** Phụ thuộc hoàn toàn vào `curl_cffi`. Nếu Cloudflare/FB cập nhật thuật toán phát hiện mới mà curl_cffi chưa kịp nâng cấp impersonate, hệ thống sẽ bị block hàng loạt.
- **Regex xử lý Header mỏng manh:** Đoạn logic tự động lấy phiên bản Chrome từ chuỗi `User-Agent` (dùng Regex `Chrome/(\d+)`) để sinh lại Header `Sec-Ch-Ua` khá rủi ro nếu một ngày định dạng UA thay đổi.
- **Rò rỉ Session Memory:** Nếu có quá nhiều Identity được set liên tục mà hàm `close()` không được gọi hợp lý, có thể sinh ra việc ứ đọng nhiều AsyncSession không được dọn dẹp.

## 5. Chi tiết các Class và Hàm

- **Biến cấu hình toàn cục (từ môi trường):**
  - `DEFAULT_IMPERSONATE`: Loại browser giả mạo (mặc định 'chrome').
  - `MAX_RETRIES`, `BASE_DELAY`, `REQUEST_TIMEOUT`: Cấu hình cho việc tự động gọi lại và timeout.
- **Hằng số `SOFT_BLOCK_SIGNATURES`**: Mảng chứa các chuỗi byte nhận diện trang challenge/captcha (vd: "checkpoint", "challenge-platform").
- **Hằng số `HEADERS_TO_STRIP`**: Set chứa các HTTP Header cần xóa bỏ trước khi đưa vào curl. Đây là bước tối quan trọng để tránh xung đột fingerprint do curl_cffi tự sinh ra thay thế.
- **Hàm `sanitize_headers(raw_headers: dict) -> dict`**: Lọc bỏ các header bị cấm (như hop-by-hop, pseudo-headers HTTP/2, và sec-ch-ua*) khỏi request, bảo vệ tính chân thực của fingerprint.
- **Hàm `is_soft_blocked(status_code: int, content: bytes, headers: dict) -> bool`**: Kiểm tra response xem có phải là 1 trang 200 OK giả mạo nhưng bên trong là captcha/checkpoint chặn bot không.
- **Hàm `is_retryable_status(status_code: int) -> bool`**: Nhận diện các HTTP status code phù hợp để retry (429, 503, 502, ...).
- **Class `AccountCheckpointError`**: Exception ném ra khi Facebook yêu cầu xác minh (checkpoint).
- **Class `ProxyBlockedError`**: Exception ném ra khi proxy bị chết hoặc block.
- **Class `StealthSessionManager`**: Class quản lý vòng đời của 1 phiên duyệt web tàng hình.
  - `__init__(...)`: Khởi tạo thông số và lock an toàn cho async.
  - `set_identity(proxy, cookies, user_agent)`: Đặt danh tính mới cho session (IP mới, cookies mới). Sẽ cưỡng chế hủy session cũ để làm mới hoàn toàn.
  - `get_session() -> AsyncSession`: Hàm bất đồng bộ (async), trả về hoặc khởi tạo (lazy init) AsyncSession của `curl_cffi` cấu hình sẵn tính năng mạo danh.
  - `request(method, url, ...) -> StealthResponse`: Phương thức nòng cốt thực hiện gọi API. Bao gồm thuật toán: Dọn dẹp header, xử lý đồng bộ User-Agent với sec-ch-ua, vòng lặp tự động retry khi gặp lỗi, bắt và tính thời gian backoff nếu bị Rate Limit, nhận diện soft-block để dừng lại.
  - `_calculate_backoff(attempt) -> float`: Tính toán số giây cần chờ trước lần retry tiếp theo, kết hợp Jitter (độ lệch ngẫu nhiên) để mô phỏng giống người.
  - `Property stats`: Cung cấp report thống kê về tỷ lệ bị block (block rate) và tổng số request.
  - `close()`: Hủy và đóng an toàn phiên.
  - `verify_fingerprint() -> dict`: Gửi một request test lên `tls.browserleaks.com` để kiểm tra JA3 TLS fingerprint xem có an toàn không.
- **Class `StealthResponse`**: Class wrap (bao bọc) kết quả trả về, lưu trữ thêm thông tin metadata như số lượt attempt và biến `is_blocked`.
  - `Property text`: Cố gắng decode bytes content ra dạng utf-8 string, kèm dự phòng lỗi font chữ.
- **Class `StealthRequestError`**: Exception ném ra khi toàn bộ các nỗ lực tự động retry đều thất bại hoàn toàn.
