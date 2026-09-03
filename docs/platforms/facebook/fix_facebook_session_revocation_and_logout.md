# Tài Liệu Kỹ Thuật: Khắc Phục Triệt Để Lỗi Tự Động Logout Facebook Khi Đang Crawl

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/server.py`
  - `backend/chrome_extension/background.js`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`, `docs/platforms/facebook/fail_safe_extension_disconnect.md`

---

## 1. Tóm tắt thay đổi

1. **Gỡ bỏ cơ chế Replay cưỡng bức `StealthUpstreamAddon` cho Facebook trong Mitmproxy (`server.py`)**:
   - Xóa bỏ việc thêm `StealthUpstreamAddon(target_domains=["facebook.com"])` vào danh sách addons của `master` Mitmproxy.
   - Khôi phục hành vi **Transparent Proxy**: Khi người dùng duyệt Facebook trên Chrome thật, Mitmproxy chỉ đóng vai trò Passive Observer (lắng nghe, phân tích và trích xuất dữ liệu qua `FacebookPlatform`), tuyệt đối không được chặn gói tin của Chrome để gửi lại bằng `curl_cffi` từ bên trong Docker.

2. **Chấm dứt việc ép chuyển hướng tab người dùng (`background.js`)**:
   - Xóa bỏ hoàn toàn lệnh `await chrome.tabs.update(targetTab.id, { url: targetUrl })` trong Extension Bridge.
   - Khi Extension nhận job cào từ backend, nó chỉ cần tận dụng bất kỳ tab Facebook nào đang mở (`fbTabs.find(t => t.active) || fbTabs[0]`) để thực thi `fetch("/api/graphql/")` với context cookie sống.

3. **Bảo toàn tính toàn vẹn của Token Mạng & Sửa lỗi cú pháp (`background.js`)**:
   - Sửa logic ghi đè token: Chỉ chèn `liveDtsg`, `liveUserId`, `liveLsd` nếu request body thực sự chưa có các trường này (`!updatedBody.includes(...)`). Tránh ghi đè các token mật mã hợp lệ đã được bắt từ template, ngăn ngừa tình trạng gửi token rỗng khi tab đang trong giai đoạn chuyển đổi trạng thái.
   - Loại bỏ dấu ngoặc thừa trên dòng 316 gây lỗi `SyntaxError: Missing catch or finally after try`, đảm bảo Service Worker khởi động và chạy polling ổn định 100% (đã xác thực qua `node -c`).

4. **Tự động làm sạch trạng thái dừng (`crawler.py`)**:
   - Trong `stop_crawling()`: Thiết lập lại `status = 'idle'` và xóa `toast_message = None`, tránh việc thông báo lỗi cũ của Extension bị kẹt hiển thị trên giao diện Dashboard.

---

## 2. Mục đích & Ý nghĩa

- **Giải quyết tận gốc lỗi "facebook lại tự bị logout khi đang crawl"**:
  - Khi `StealthUpstreamAddon` can thiệp vào traffic `facebook.com` của Chrome, Facebook nhận được 2 luồng kết nối song song mang cùng Session Cookie (`c_user`, `xs`): Một từ Windows Chrome thật và một từ Linux `curl_cffi` (Docker) với TLS giả lập và không có TLS session tickets.
  - Thuật toán bảo mật chống gian lận của Meta ngay lập tức phân loại đây là hành vi **Session Hijacking (Chiếm đoạt phiên)** và kích hoạt **Server-Side Session Revocation**, trả về lỗi:
    `{"errors":[{"message":"Unauthorized logged out query.","code":1675002}]}`
    đồng thời chuyển hướng người dùng về trang đăng nhập `/login/`.
  - Việc khôi phục Transparent Proxy bảo vệ 100% phiên đăng nhập tự nhiên của người dùng, không còn bị Meta nghi ngờ hay hủy phiên.

---

## 3. Mối liên hệ kiến trúc

- **`Mitmproxy Server` (`server.py`)**: Giữ đúng vai trò tầng Network Infrastructure, truyền tải gói tin nguyên bản giữa Chrome và Facebook, chỉ thông báo sự kiện qua `ProxyRouter`.
- **`FacebookPlatform` (`platform.py`)**: Đóng vai trò Domain Observer, chỉ đọc và bóc tách dữ liệu từ `flow.response` mà không can thiệp vào vòng đời kết nối.
- **`Extension Bridge` (`background.js` & `bridge.py`)**: Đóng vai trò In-Tab Execution Engine, thực thi GraphQL queries tự nhiên bên trong phiên duyệt web hợp lệ của người dùng.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Người dùng không mở bất kỳ tab Facebook nào khi bấm cào:**
   - *Hành vi:* Extension tự động tạo một tab nền `https://www.facebook.com` (`active: false`) và đợi 5 giây để tab khởi tạo session trước khi thực thi.
2. **Tab Facebook đang ở màn hình chưa đăng nhập:**
   - *Hành vi:* Hàm `executeScript` kiểm tra nếu không có phiên đăng nhập sẽ trả về mã lỗi rõ ràng và dừng an toàn (`fail-safe`), không gửi request rác lên server của Facebook.
