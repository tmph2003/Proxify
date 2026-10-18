# 🔌 Tách Biệt Core Request Tracker & Thư Mục `private/` (Clean Architecture & Open-Core)

## 1. Tóm tắt thay đổi
Toàn bộ các module liên quan đến crawling, scraping, bot automation, giải mã tin nhắn nền tảng cụ thể (Facebook, Zalo, YouTube, TikTok, CloakBrowser, v.v.) đã được tách hoàn toàn khỏi Proxify Core và gom về thư mục gốc `private/` (được cấu hình trong `.gitignore`). Đồng thời, hai tài liệu gốc `README.md` và `README_vi.md` đã được viết lại hoàn toàn để phản ánh đúng bản chất của Proxify là một **High-Performance HTTP/HTTPS/WebSocket Request Tracker & Traffic Inspection Framework**.

Các thay đổi chính trên Core bao gồm:
- **Core Backend (`backend/proxify/`)**:
  - `sdk/context.py` & `core/router.py`: Bổ sung cơ chế `register_record_filter(predicate)` và `should_skip_record(domain, path, url)` để các extension tự đăng ký bộ lọc loại trừ lưu trữ DB mà không làm bẩn `server.py`. Thay thế kiểm tra tên cứng `"YouTube Enhancer"` trong `ProxyRouter.route_responseheaders` bằng thuộc tính đa hình `getattr(m, "mutates_js", True)`.
  - `server.py`: Xóa import trực tiếp `proxify.utils.youtube_utils` khỏi `V1GlobalObserver.handle_response`.
  - `core/worker.py`: Loại bỏ toàn bộ các phương thức xử lý GraphQL/Post của Facebook và đường dẫn `tokens.json`; chuyển `BackgroundWorker` thành bộ điều phối sự kiện CQRS tổng quát thông qua `register_topic_handler(topic, handler)`.
  - `dashboard.py` & `capture_addon.py`: Loại bỏ route `/api/stealth/stats` (vốn import `facebook.crawler`) và logic kiểm tra chuỗi `'zalo'` khi stream file `.js`.
  - `plugins/tls_spoofer.py` & `utils/stealth.py`: Giữ lại TLS/JA3 Fingerprint Spoofing phục vụ việc vượt qua anti-bot (Cloudflare/Akamai) khi tracking request, nhưng loại bỏ hoàn toàn header nội bộ `x-proxify-crawler`, danh sách domain mặc định của TikTok và các comment/header đặc thù của Facebook.
  - `sdk/loader.py`: Tự động quét extension từ `private/extensions/` (hoặc biến môi trường `PROXIFY_EXTENSIONS_DIR`) và thêm `private/shared/` vào `sys.path`.
- **Chrome Extension (`backend/chrome_extension/`)**:
  - Lưu trữ bản đầy đủ chứa tính năng trích xuất Cookie Facebook / GraphQL / Bridge Polling vào `private/chrome_extension_fb/`.
  - Rút gọn `backend/chrome_extension/` về đúng chức năng: **1-Click Proxy Toggle**, hiển thị trạng thái kết nối Proxy trên Badge, và bật/tắt **DB Capture Integration** theo danh sách domain tùy chọn. Loại bỏ quyền `cookies`, `scripting`, `webRequest`, `content.js` và `youtube_anti_afk.js`.
- **Frontend (`frontend/src/`), Hạ tầng (`Dockerfile`, `docker-compose.yml`) & Tài liệu (`README.md`, `README_vi.md`)**:
  - Gỡ bỏ route/icon/CSS cứng của Zalo & Facebook khỏi `App.tsx`, `MainLayout.tsx`, `index.css`.
  - Gỡ bỏ `playwright`, `CloakBrowser` và cấu hình DNS nội bộ đặc thù khỏi `Dockerfile` và `docker-compose.yml`.
  - Viết lại `README.md` và `README_vi.md` tập trung vào tính năng Request Tracking, TLS/JA3 Fingerprint Spoofing, 1-Click Chrome Extension và kiến trúc Extension SDK.

## 2. Mục đích & Ý nghĩa
- **Đúng bản chất sản phẩm**: Đưa Proxify Core và tài liệu giới thiệu trở về đúng bản chất là một hệ thống **HTTP/HTTPS Request Tracker & Interceptor** chuẩn mực, gọn nhẹ và tổng quát.
- **Tuân thủ Clean Architecture & SOLID (DIP / OCP)**: Tầng Core (Application & Infrastructure) không còn phụ thuộc ngược vào tầng Plugin/Platform cụ thể. Mọi nhu cầu mở rộng (filter request, xử lý worker sự kiện, can thiệp nội dung JS) đều đi qua abstraction của `ExtensionContext` và `ProxyRouter`.
- **Bảo mật & Sạch sẽ trên Git**: Toàn bộ các công cụ private phục vụ bài toán nghiệp vụ riêng được gom vào một thư mục duy nhất `private/` và được `.gitignore` bảo vệ, không lo rò rỉ lên kho mã nguồn chung mà không cần viết lại lịch sử Git.

## 3. Mối liên hệ
- Liên kết trực tiếp tới hệ thống Plugin/Extension SDK (`backend/proxify/sdk/loader.py`, `backend/proxify/sdk/context.py`), bộ định tuyến (`backend/proxify/core/router.py`), máy chủ proxy (`backend/proxify/server.py`), tiện ích Chrome (`backend/chrome_extension/`), giao diện React (`frontend/src/App.tsx`), và tài liệu gốc (`README.md`, `README_vi.md`).
- Các extension nằm trong `private/extensions/` vẫn được nạp tự động khi chạy local hoặc qua Docker volume `./private/extensions:/app/extensions` nếu thư mục này tồn tại.

## 4. Rủi ro (Risks & Edge Cases)
- **Môi trường chỉ có Core (không có thư mục `private/`)**: Khi clone repo mới không có thư mục `private/`, `ExtensionLoader` sẽ kiểm tra sự tồn tại của thư mục và bỏ qua một cách an toàn mà không phát sinh lỗi `FileNotFoundError` hay `ImportError`.
- **Tương thích ngược cho Private Extensions**: Các extension cũ trong `private/extensions/` có thể vẫn gọi `import proxify.platforms...` hoặc `proxify.utils.circuit_breaker`. Điều này đã được xử lý thông qua cơ chế nạp `private/shared` vào `sys.path` và đăng ký alias `sys.modules` ngay trong `initialize()` của từng extension riêng biệt.
