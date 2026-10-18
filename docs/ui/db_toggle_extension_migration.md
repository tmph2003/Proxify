# Di Chuyển Bộ Điều Khiển Ghi DB & Lọc Domain Ghi DB Sang Chrome Extension (CQS & SRP Refactoring)

## 1. Tóm tắt thay đổi
- **Tích hợp bộ điều khiển Ghi DB & Lọc Domain Ghi DB (`dbAllowedDomains`) vào [`backend/chrome_extension/popup.html`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.html) và [`popup.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.js):**
  - Thêm thẻ điều khiển **🗄️ Ghi dữ liệu vào DB** kèm mục mở rộng **🎯 Lọc Ghi DB (Tất cả / N domain)** ngay bên trong thẻ.
  - Tự động nhận diện **Domain của Tab đang mở hiện tại** (`activeTabDomain`), kết hợp với các preset chính (`facebook.com`, `zalo.me`, `youtube.com`), danh sách từ `/api/domains` và ô nhập domain tùy chỉnh (`+ Thêm`).
  - Tự động lưu cấu hình lọc domain tức thì qua `POST /api/toggle_db` (`{ allowed_domains: [...] }`) ngay khi người dùng tích chọn hoặc thêm/xóa domain.
- **Tách biệt hoàn toàn Write Config khỏi Read Filter Bar trên [`frontend/src/pages/Dashboard.tsx`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/frontend/src/pages/Dashboard.tsx):**
  - Gỡ bỏ hoàn toàn cả 2 nút `#dbToggleBtn` (`🟢 Ghi DB: BẬT/TẮT`) và `#dbDomainBtn` / `#dbDomainDropdown` (`🎯 Lọc Ghi DB`) khỏi thanh công cụ `filter-bar` của `Dashboard.tsx`.
  - Thanh công cụ trên `Dashboard.tsx` giờ chỉ giữ đúng trách nhiệm **Read/Query Filter** (lọc hiển thị danh sách gói tin trên màn hình).

---

## 2. Mục đích & Ý nghĩa
- **Khắc phục triệt để lỗi thiết kế "Con gà - Quả trứng" (Chicken-and-Egg Deadlock) của bộ lọc `🎯 Lọc Ghi DB` cũ:**
  - Trên `Dashboard.tsx` cũ, danh sách domain trong `🎯 Lọc Ghi DB` chỉ lấy từ `GET /api/domains` (`SELECT domain, COUNT(*) FROM requests`). Khi chưa bật Ghi DB hoặc bảng `requests` trống, danh sách này luôn rỗng (*"Chưa có domain nào"*), khiến người dùng **không thể chọn lọc domain trước khi bật Ghi DB**, và khi đã chọn 1 domain thì các domain mới không bao giờ xuất hiện thêm.
  - Khi đưa sang `Proxify Helper` Extension, tiện ích tự động lấy luôn **hostname của Tab đang mở**, cộng với các preset nền tảng và ô nhập tay, cho phép người dùng khóa mục tiêu ghi DB (ví dụ chỉ ghi `facebook.com`) **trước cả khi bật nút Ghi DB**.
- **Tuân thủ nguyên lý Command-Query Separation (CQS) & Single Responsibility Principle (SRP) trên UI:**
  - Trước đây, thanh `filter-bar` trên `Dashboard.tsx` trộn lẫn các bộ lọc hiển thị (**Query/Read Filters**: `Tất cả Domains`, `Methods`, `Status`) với cấu hình điều khiển luồng ghi Server (**Command/Write Config**: `🎯 Lọc Ghi DB`, `🟢 Ghi DB`), gây nhầm lẫn giữa việc "lọc gói tin đang xem" và "lọc gói tin lưu vào DB". Việc chuyển toàn bộ cụm điều khiển Ingestion/Write sang `Proxify Helper` giúp `filter-bar` của Dashboard thuần khiết 100% là bộ lọc hiển thị.

---

## 3. Mối liên hệ
- **[`backend/chrome_extension/popup.html`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.html) & [`popup.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.js):** Giao tiếp với [`backend/proxify/dashboard.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/dashboard.py) qua `/api/config`, `/api/domains` và `/api/toggle_db`, đồng thời tác động trực tiếp tới bộ lọc `db_allowed_domains` trong [`V1GlobalObserver.handle_response`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py#L124-L130).
- **[`frontend/src/pages/Dashboard.tsx`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/frontend/src/pages/Dashboard.tsx):** Được giải phóng khỏi các state điều khiển ghi DB (`showDbDomainDropdown`, `dbAllowedDomains`, `saveDbDomains`, `handleToggleDb`).

---

## 4. Rủi ro (Risks & Edge Cases)
- **Phụ thuộc điều khiển Ingestion vào Chrome Extension:** Toàn bộ thao tác bật/tắt `db_integration_enabled` và cấu hình `db_allowed_domains` hiện nằm trên popup của `Proxify Helper` Extension. Nếu sử dụng Proxify từ thiết bị ngoài (như điện thoại di động) mà không mở Chrome, người dùng cần cấu hình qua biến môi trường `DB_INTEGRATION_ENABLED` hoặc gọi REST API `/api/toggle_db`.
- **Chuẩn hóa tên miền (Subdomain Matching):** Tại [`server.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py#L128), logic kiểm tra là `domain == d or domain.endswith('.' + d)`. Do đó, khi Extension tự động cắt tiền tố `www.` từ tab hiện tại (ví dụ `www.facebook.com` -> `facebook.com`), bộ lọc sẽ tự động khớp chính xác cho cả `facebook.com`, `www.facebook.com`, `m.facebook.com` và `web.facebook.com`.
