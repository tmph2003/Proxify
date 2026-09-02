# Tóm tắt thay đổi
Đã thực hiện chuyển đổi kiến trúc Frontend từ mô hình Server-Side Rendering (dùng các file HTML template của `aiohttp`) sang mô hình Single Page Application (SPA) sử dụng **React + Vite + TypeScript**.

- **Khởi tạo Vite project** tại thư mục `proxify/ui/frontend`.
- **Cấu hình React Router**: Đã thiết lập các route `/`, `/facebook`, `/zalo` dùng chung layout `MainLayout`.
- **Chuyển đổi giao diện**: Đã migrate CSS từ `style.css` và `zalo.css` vào `index.css`. Code HTML từ các file `index.html`, `facebook.html`, `zalo.html` đã được bóc tách và parse sang dạng component TSX của React. Các JS nội tuyến đã được gỡ bỏ để đảm bảo bảo mật và sẽ được quản lý bằng React Hooks.
- **Tích hợp Backend**: Đã sửa file `dashboard.py` để trỏ aiohttp server tới thư mục `dist/` do Vite build ra. Các route `/`, `/zalo`, `/facebook` giờ sẽ trả về `index.html` của SPA.

# Mục đích & Ý nghĩa
- **Bảo mật Source Code (User Requirement):** Mô hình cũ render trực tiếp các file template HTML chứa script JS không được mã hóa (inspect element / F12 có thể xem được toàn bộ logic). Mô hình mới sử dụng Vite để bundle và minify mã nguồn (JS/TS), khiến việc xem mã nguồn gốc hoặc thao túng logic frontend từ F12 trở nên vô cùng khó khăn.
- **Trải nghiệm người dùng:** SPA cho phép render trang động, mượt mà hơn khi chuyển tab (ví dụ: Zalo, Facebook) mà không cần reload trang.

# Mối liên hệ
- Ảnh hưởng trực tiếp tới cách `dashboard.py` (Backend) phục vụ giao diện (thay vì đọc folder `templates` thì đọc folder `frontend/dist`).
- Thay thế toàn bộ mã ở `ui/templates/*` và các JS rời rạc trong `ui/static/js/`.
- Backend APIs (WebSockets và REST API như `/api/requests`, `/api/stats`) vẫn giữ nguyên, Frontend mới cần gọi lại các API này thông qua `axios` hoặc `fetch`.

# Rủi ro (Risks & Edge Cases)
- **Logic cũ bị mất:** Hiện tại các file React component (`Zalo.tsx`, `Facebook.tsx`, `Dashboard.tsx`) đang chứa UI skeleton. Logic thao tác (WebSocket, DOM manipulation) từng có trong các script JS cũ (`zalo.js`) chưa được chuyển sang React Hooks hoàn chỉnh. Cần thực hiện nối API và viết lại Hooks ở bước tiếp theo để web hoạt động đầy đủ chức năng.
- **Phát sinh lỗi Routing (404):** Nếu có một path lạ mà Backend chưa bắt (`add_get`), server có thể trả về 404 thay vì fallback về SPA `index.html`.
- **Asset path:** Các hình ảnh trong `/assets/` cần đảm bảo được load đúng từ public của SPA và tương thích đường dẫn tuyệt đối/tương đối.
