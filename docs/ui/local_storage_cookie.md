# Chuyển đổi Cookie sang LocalStorage hoàn toàn

## Tóm tắt thay đổi
1. **Frontend (UI - `facebook.html`)**:
   - Sửa hàm `saveCookie()`: Chỉ lưu cookie vào `localStorage` của trình duyệt. Xóa hoàn toàn lệnh `fetch('/api/facebook/cookie', ...)` gửi cookie lên server để lưu trữ.
   - Sửa hàm `loadCookieStatus()`: Chỉ đọc cookie từ `localStorage` để hiển thị trạng thái lên UI, không còn gọi API lấy cookie từ server.
2. **Backend (API - `proxify/platforms/facebook/api.py`)**:
   - Xóa bỏ biến toàn cục `IN_MEMORY_COOKIES` (không còn lưu cookie trên RAM của server Python).
   - Xóa bỏ các API route `POST /api/facebook/cookie` và `GET /api/facebook/cookie`.
   - Các API crawl (`crawl_posts`, `crawl_comments`, `bulk_action`) giờ đây hoàn toàn phụ thuộc vào tham số `cookie` được truyền trực tiếp từ UI.

## Mục đích & Ý nghĩa
- Củng cố quy tắc "Tuyệt đối không lưu cookies ở database và bắt buộc phải lưu trên local storage của browser client".
- Server trở thành dạng *Stateless* đối với Cookie: nó chỉ nhận cookie qua payload của từng request crawl và dùng xong rồi bỏ, không lưu trữ (dù là trên RAM hay Ổ cứng). Bảo mật dữ liệu người dùng được đẩy lên mức tuyệt đối.

## Rủi ro (Risks & Edge Cases)
- **Extension Chrome bị ảnh hưởng**: Tính năng "Đồng bộ Cookie tự động vào Proxify" của extension cũ sẽ bị lỗi mạng (404 Not Found) do endpoint `/api/facebook/cookie` đã bị xóa. Người dùng bắt buộc phải copy cookie và paste trực tiếp vào UI. (Nếu cần, có thể update Extension để extension gửi cookie thẳng vào `localStorage` của tab Dashboard, nhưng tính năng hiện tại đã bị hủy bỏ theo yêu cầu bảo mật).
