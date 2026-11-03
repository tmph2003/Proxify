# Khắc phục lỗi CORS & Host Permissions giữa Chrome Extension và Dashboard API

## 1. Tóm tắt thay đổi
- **`backend/proxify/dashboard.py`**: Bổ sung `_cors_middleware` vào `aiohttp.web.Application` của `Dashboard` để trả về đầy đủ các header `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers` và xử lý preflight request `OPTIONS` (HTTP 204).
- **`backend/chrome_extension/manifest.json`**: Khôi phục khai báo `"host_permissions": ["http://127.0.0.1/*", "http://localhost/*"]` theo chuẩn Least Privilege để cho phép popup thực hiện cross-origin request tới local server.
- **`backend/chrome_extension/popup.js`**: Tự động phát hiện và chuyển hướng (auto-correct) khi người dùng hoặc bộ nhớ đệm `chrome.storage.local` lưu nhầm cổng Proxy (`:8080`) thay vì cổng Control Plane / Dashboard API (`:8888`).

## 2. Mục đích & Ý nghĩa
- **Giải quyết lỗi `TypeError: Failed to fetch` (MẤT KẾT NỐI) trên Popup**:
  - Trong đợt refactor tách biệt Core (`72c5911`), `host_permissions` trong `backend/chrome_extension/manifest.json` đã bị lược bỏ hoàn toàn. Khi không có `host_permissions`, mọi lệnh `fetch("http://127.0.0.1:8888/api/...")` từ `chrome-extension://<id>/popup.html` đều bị trình duyệt áp dụng chính sách CORS nghiêm ngặt.
  - Vì `Dashboard` (`aiohttp`) chưa cấu hình CORS middleware, các gói tin `GET /api/config` và preflight `OPTIONS /api/toggle_db` bị trình duyệt chặn ngay tại tầng mạng của Extension, dẫn đến trạng thái **MẤT KẾT NỐI** dù đổi sang cổng `8888`.
- **Tác dụng kép (Defense-in-Depth)**:
  - Việc thêm `_cors_middleware` ở Backend giúp popup hoạt động **ngay lập tức** khi restart container `proxify_app` mà không bắt buộc người dùng phải vào `chrome://extensions` bấm Reload tiện ích.
  - Việc bổ sung `host_permissions` cho `127.0.0.1` và `localhost` đảm bảo chuẩn Manifest V3 khi người dùng reload hoặc cài mới tiện ích.

## 3. Mối liên hệ
- Liên kết trực tiếp giữa tầng Presentation của Extension (`backend/chrome_extension/popup.js`, `manifest.json`), Reverse Proxy (`frontend/nginx.conf` trên cổng `8888`) và Control Plane API (`backend/proxify/dashboard.py`).

## 4. Rủi ro (Risks & Edge Cases)
- **Bảo mật (CORS `*` trên Dashboard API)**: Các API `/api/config` và `/api/toggle_db` chỉ lắng nghe ở môi trường local phục vụ phát triển/điều khiển proxy. Tuy nhiên, nếu người dùng phơi bày cổng `8888` ra mạng công cộng (public internet) mà không có lớp xác thực, trang web bên thứ ba có thể gọi vào API local. Với phạm vi local development tool (`127.0.0.1`), việc mở CORS là hoàn toàn an toàn và cần thiết cho Chrome Extension.
