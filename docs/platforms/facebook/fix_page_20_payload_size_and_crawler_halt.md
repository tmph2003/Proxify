# Khắc Phục Lỗi Dừng Cào Tại Trang 20: Nginx 413 Payload Too Large & Aiohttp Buffer Limit

## 1. Tóm tắt thay đổi
* **Cấu hình Nginx (`frontend/nginx.conf`)**:
  * Bổ sung `client_max_body_size 50M;` vào `server` block.
  * Đã đồng bộ trực tiếp vào container `proxify_ui` và reload Nginx nóng (`nginx -s reload`).
* **Cấu hình Backend Dashboard (`backend/proxify/dashboard.py`)**:
  * Thiết lập `self.app = web.Application(client_max_size=50 * 1024 * 1024)` nhằm nâng giới hạn buffer request body của Aiohttp lên 50MB (mặc định của Aiohttp chỉ là 1MB).
* **Cấu hình Chrome Extension (`backend/chrome_extension/background.js`)**:
  * Tăng thời gian chờ lệnh `fetch()` trong tab Facebook từ 35s lên 60s cho các trang sâu.
  * Bổ sung kiểm tra HTTP status code khi POST kết quả job về `/api/facebook/bridge/result`. Nếu server trả về lỗi (như 413, 500), Extension sẽ in log chi tiết thay vì nuốt lỗi âm thầm.
* **Cấu hình Crawler (`backend/proxify/platforms/facebook/crawler.py`)**:
  * Tăng `bridge_timeout` từ 40s lên 65s trong `_safe_request()` để tương thích với thời gian thực thi của Extension trên các trang có payload lớn.
  * Cải tiến `_check_old_posts()`: Bổ sung log theo dõi tiến độ quét bài cũ (`Consecutive old pages: x/3`) và kiểm tra chặt chẽ điều kiện `start_ts`.

---

## 2. Mục đích & Ý nghĩa
* **Giải quyết dứt điểm nguyên nhân gốc rễ (Root Cause) của lỗi dừng cào ở Trang 20**:
  * Khi cào sâu đến trang 18 - 20, payload GraphQL của Facebook phình to lên tới hơn 1.1MB (1,169,789 bytes).
  * Khi Extension Bridge gửi gói kết quả này về endpoint `/api/facebook/bridge/result` thông qua cổng 8888, Nginx (container `proxify_ui`) với giới hạn mặc định `client_max_body_size 1M` đã lập tức từ chối và phản hồi lỗi **`HTTP 413 Request Entity Too Large`**.
  * Backend không nhận được kết quả, chờ hết 40s timeout rồi retry lần 2. Lần 2 tiếp tục bị Nginx chặn 413, khiến backend nhận định Extension mất kết nối hoặc bị Facebook soft-block và dừng cào với status `503`.
  * Nâng giới hạn Nginx và Aiohttp lên 50MB giúp payload lớn đi qua thông suốt, crawler tiếp tục chạy qua trang 20, 30, 40... mà không bị nghẽn.

---

## 3. Mối liên hệ
* **`frontend/nginx.conf`**: Cổng ngõ Reverse Proxy tiếp nhận toàn bộ traffic từ Extension Bridge và Browser.
* **`backend/proxify/dashboard.py`**: Web server Aiohttp xử lý các API endpoint của backend.
* **`backend/chrome_extension/background.js`**: Client Extension chạy trong trình duyệt người dùng, trực tiếp thu thập dữ liệu GraphQL trong ngữ cảnh tab Facebook.
* **`backend/proxify/platforms/facebook/crawler.py`**: Bộ điều phối tiến trình cào dữ liệu Group Feed.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Tiêu thụ RAM khi payload cực lớn**: Với giới hạn 50MB, nếu payload đạt kích thước lớn, RAM container có thể tăng nhẹ trong chốc lát trong quá trình JSON parsing. Tuy nhiên Docker host có thừa tài nguyên để xử lý.
* **Rate limit từ phía Facebook**: Khi vượt qua trang 20, Facebook có thể tăng độ trễ phản hồi hoặc yêu cầu captcha nếu tần suất request quá dày. Hệ thống đã có cơ chế độ trễ ngẫu nhiên (Gaussian crawl delay) và circuit breaker để giảm thiểu rủi ro này.
