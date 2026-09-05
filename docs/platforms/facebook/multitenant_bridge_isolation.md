# Định danh & Cô lập Đa Client (Multi-Tenant Extension Bridge)

## Tóm tắt thay đổi
1. **`backend/proxify/platforms/facebook/bridge.py`**:
   - Cải tiến `ExtensionBridge` từ hàng đợi đơn lẻ sang cấu trúc hàng đợi phân lập theo từng client (`client_queues: Dict[str, Dict[str, dict]]`).
   - Quản lý nhịp tim và trạng thái kết nối độc lập cho từng client (`client_last_poll: Dict[str, float]`).
   - Cập nhật các phương thức `is_connected`, `has_jobs`, `get_job`, `execute_request`, và `complete_job` hỗ trợ tham số `client_id` (mặc định `"default"` để đảm bảo tương thích ngược 100%).
2. **`backend/proxify/platforms/facebook/api.py`**:
   - Xây dựng kho lưu trữ cookie và template phân tầng `TENANT_COOKIES` và `TENANT_TEMPLATES` theo `client_id`.
   - Cung cấp proxy class `_TenantCookieProxy` bọc quanh `TENANT_COOKIES['default']` để giữ nguyên tính tương thích với code cũ dùng `IN_MEMORY_COOKIES`.
   - Cập nhật các API routes:
     - `GET /api/facebook/bridge/jobs`: Nhận `client_id` qua query parameter hoặc header `X-Client-ID` để chỉ trả về job của client đó.
     - `POST /api/facebook/bridge/result`: Nhận kết quả kèm `client_id`.
     - `POST /api/facebook/cookie`: Nhận và lưu cookie/template phân tầng theo `client_id`.
     - `POST /api/facebook/crawl` & `/crawl_comments`: Tiếp nhận `client_id` và truyền vào crawler task.
3. **`backend/proxify/platforms/facebook/crawler.py`**:
   - Khởi tạo `FacebookCrawler` với `client_id` (mặc định `"default"`).
   - Truyền `client_id` vào mọi lệnh gọi `bridge.is_connected(...)` và `bridge.execute_request(...)`.
   - Cập nhật các alias `start_crawler` và `crawl_post_comments` hỗ trợ `client_id`.
4. **`backend/chrome_extension`**:
   - **`popup.html`**: Bổ sung khu vực cấu hình mở rộng (Collapsible Settings) cho phép người dùng cấu hình **Server URL** (mặc định `http://127.0.0.1:8888`) và **Client ID / Tenant** (mặc định `default`).
   - **`popup.js`**: Tải và lưu cấu hình vào `chrome.storage.local`. Gửi kèm `client_id` khi bấm nút bắn cookie vào Proxify.
   - **`background.js`**: Đọc cấu hình từ `chrome.storage.local`. Định tuyến polling job theo `${serverUrl}/api/facebook/bridge/jobs?client_id=${clientId}` và gửi kèm `client_id` khi trả kết quả hoặc đồng bộ cookie/template.
5. **`backend/tests/test_bridge_multitenant.py`**:
   - Tạo bộ unit test xác minh cô lập hàng đợi giữa các client, cô lập heartbeat và tính tương thích ngược.

## Mục đích & Ý nghĩa
- **Xóa bỏ triệt để rủi ro Cross-Tenant Leak & Cướp Job**: Trước đây, khi nhiều client cùng cài Extension và kết nối về 1 backend Docker tập trung, Extension của Client B có thể lấy nhầm job của Client A. Điều này dẫn đến việc session của B bị dùng để cào dữ liệu của A, gây lỗi `1357001` và lộ lọt dữ liệu bảo mật giữa các khách hàng.
- **Hỗ trợ Scale Đa Client (Multi-Client Scalability)**: Cho phép 1 backend Docker duy nhất có thể phục vụ cùng lúc hàng chục hoặc hàng trăm máy tính client độc lập. Mỗi client tự cào dữ liệu qua chính IP dân cư và trình duyệt thật của họ, giải phóng server khỏi việc phải mua và quản lý proxy dân cư đắt đỏ.
- **Linh hoạt cấu hình mạng**: Khách hàng có thể kết nối Extension từ xa về backend qua domain công khai hoặc IP máy chủ thay vì bị gán cứng vào `127.0.0.1:8888`.

## Mối liên hệ
- `backend/chrome_extension` (Client Edge) $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py` & `api.py` (Master Hub): Giao thức giao tiếp định danh hai chiều thông qua `client_id`.
- `backend/proxify/platforms/facebook/crawler.py` $\rightarrow$ `bridge.py`: Điều phối luồng request của từng phiên cào vào đúng hàng đợi của khách hàng yêu cầu.
- `backend/proxify/platforms/facebook/auth.py` $\leftrightarrow$ `api.py`: Quản lý template GraphQL độc lập giữa các phiên làm việc của từng client.

## Rủi ro (Risks & Edge Cases)
1. **Client ID bị trùng lặp giữa các máy tính khác nhau**:
   - Nếu hai nhân viên/khách hàng khác nhau cùng đặt chung một `client_id` (ví dụ giữ nguyên `default`), công việc của hai máy này sẽ rơi vào cùng một hàng đợi.
   - *Khuyến nghị*: Khi triển khai SaaS, mỗi client nên được cấp một chuỗi UUID ngẫu nhiên hoặc Token xác thực riêng từ hệ thống quản lý tài khoản.
2. **Client tắt máy hoặc Extension ngắt kết nối giữa chừng**:
   - Nếu client đang cào mà đóng trình duyệt Chrome, job sẽ timeout sau 65s và chuyển sang trạng thái dừng an toàn (không bị checkpoint tài khoản). Cần thông báo rõ trên giao diện web để người dùng biết máy trạm đang offline.
