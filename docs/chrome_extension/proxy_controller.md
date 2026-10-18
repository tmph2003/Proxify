# 🧩 Chrome Extension — Core Proxy Toggle & DB Capture Controller

## 1. Tóm tắt thay đổi
Tiện ích mở rộng Chrome tại `backend/chrome_extension/` đã được tái cấu trúc và rút gọn tối đa để chỉ phục vụ mục đích điều khiển Proxy và cấu hình lưu trữ Request Tracking cho Proxify Core:
- Xóa các file `content.js` và `youtube_anti_afk.js` khỏi Core (đã chuyển bản gốc đầy đủ sang `private/chrome_extension_fb/`).
- Cập nhật `manifest.json` (v2.0.0): Chỉ giữ lại quyền `proxy` và `storage`, loại bỏ `cookies`, `scripting`, `webRequest` và `<all_urls>`.
- Viết lại `background.js`, `popup.html`, và `popup.js`: Chỉ giữ lại tính năng **1-Click Proxy Toggle** (`127.0.0.1:8080`), đồng bộ cấu hình **DB Integration Toggle** và bộ lọc **Allowed Domains** với Dashboard API (`/api/config`, `/api/toggle_db`).

## 2. Mục đích & Ý nghĩa
- **Loại bỏ hoàn toàn logic Crawl/Platform**: Không còn tự động đọc cookie `c_user`/`xs` của Facebook, không bắt cặp header GraphQL hay nhận lệnh điều khiển tab (Bridge Job Polling).
- **Giảm thiểu quyền truy cập (Least Privilege)**: Việc bỏ quyền đọc cookie, đọc request mạng và chèn script trên mọi trang web giúp extension nhẹ hơn, an toàn hơn và đúng chuẩn một công cụ bật/tắt Proxy phục vụ debug & tracking request.

## 3. Mối liên hệ
- Giao tiếp trực tiếp với `backend/proxify/dashboard.py` qua các endpoint REST chuẩn của Core: `GET /api/config`, `POST /api/config`, và `POST /api/toggle_db`.
- Điều hướng lưu lượng trình duyệt Chrome đi qua cổng proxy `backend/proxify/server.py` (mặc định `127.0.0.1:8080`).

## 4. Rủi ro (Risks & Edge Cases)
- **Thay đổi cổng Proxy/Dashboard**: Nếu người dùng đổi cổng Dashboard (mặc định `8888`), có thể cấu hình trực tiếp trong ô `Dashboard API URL` trên giao diện Popup của Extension.
- **Lưu trữ bộ nhớ cục bộ**: Khi nâng cấp từ bản cũ trên trình duyệt Chrome, người dùng nên bấm **Reload** extension trong `chrome://extensions` để Service Worker (`background.js`) áp dụng manifest mới và xóa các listener `webRequest` cũ.
