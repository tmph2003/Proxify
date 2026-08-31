# Sửa lỗi mất Cookie khi UI truyền vào do conflict file API và Plugin

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/plugins/facebook.py` để loại bỏ hoàn toàn cơ chế gọi Playwright fetcher cũ.
- Đồng bộ lại logic `_handle_facebook_crawl` trong `plugins/facebook.py` để giống với `platforms/facebook/api.py`.
- Truyền đúng `client_cookie=cookie_str` vào hàm `start_crawler()`.

## Mục đích & Ý nghĩa
- Trong quá trình chạy thực tế, `proxify/server.py` đã tự động load `proxify/plugins/facebook.py` qua `capture_addon.py`.
- Do đó, route `/api/facebook/crawl` của `plugins/facebook.py` đã đè (override) lên route của `platforms/facebook/api.py`.
- Lỗi xuất phát từ việc `plugins/facebook.py` bản cũ có inject cookie thẳng vào dictionary của biến `template` (chứ không phải nested bên trong `"feed"]["headers"]["cookie"]`), và KHÔNG truyền `client_cookie` vào `start_crawler()`. Hệ quả là `_resolve_cookie()` không thể tìm thấy cookie nào và luôn văng lỗi "Không tìm thấy cookies Facebook" dù người dùng có paste cookie trên giao diện.

## Mối liên hệ
- File sửa đổi chính: `proxify/plugins/facebook.py`
- Ảnh hưởng đến: Quá trình phân tích cookie của `proxify/platforms/facebook/crawler.py` (`_resolve_cookie()`).
- Bây giờ crawler có thể đọc được chính xác Cookie mà người dùng truyền lên từ Giao diện thông qua trường `client_cookie`.

## Rủi ro (Risks & Edge Cases)
- Sự tồn tại song song của `platforms/facebook/api.py` và `plugins/facebook.py` đang gây ra nợ kỹ thuật (Technical Debt) lớn vì bị trùng lặp route. Trong tương lai, hệ thống nên xóa bỏ một trong hai file hoặc merge chúng lại để tránh tình trạng sửa file này nhưng file kia lại chạy (như lỗi vừa gặp).
- Cookie paste từ UI có thể hết hạn giữa chừng khi Crawler chạy quá lâu. Người dùng sẽ phải tự thay cookie nếu gặp lỗi redirect login.
