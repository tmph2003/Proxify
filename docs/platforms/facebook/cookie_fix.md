# Sửa lỗi Cookie Facebook

## Tóm tắt thay đổi
1. Sửa câu lệnh SQL trích xuất Cookie trong `proxify/platforms/facebook/template_fetcher.py` và `proxify/platforms/facebook/token_store.py` thành:
   `AND request_headers ILIKE '%c_user=%' AND request_headers ILIKE '%xs=%'`
2. Đổi hàm `get_cookies_and_ua_from_db` trong `token_store.py` để trả về thẳng chuỗi cookie thô (raw cookie string) thay vì parse thành dict.
3. Tái cấu trúc hàm `_resolve_cookie` trong `proxify/platforms/facebook/crawler.py`:
   - Biến thành hàm bất đồng bộ (`async`).
   - Đổi thứ tự ưu tiên lấy cookie thành: `client_cookie` > `Cookie từ Database` > `Cookie từ template (cũ)`.
4. Xóa bỏ logic fallback vụn vặt và thừa thãi nằm rải rác trong `_execute_crawl_group_feed`, `_execute_crawl_comments` và `_scrape_comments_from_page`.

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Crawler lấy nhầm cookie ẩn danh (không có auth) hoặc ưu tiên lấy cookie trong template đã hết hạn, bỏ qua hoàn toàn cookie tươi vừa mới login được lưu trong Database, dẫn tới việc bị Facebook báo lỗi `1357001` dù mới login xong.
- **Sửa lỗi:** Thay đổi này ép hệ thống phải lấy đúng cookie chứa `xs` (session secret) và ưu tiên lấy cookie trực tiếp từ Database (do Mitmproxy bắt được khi người dùng duyệt web) trước khi dùng đồ cũ trong template, đảm bảo crawler luôn chạy trên session tươi nhất. Tập trung logic (DRY) ở `_resolve_cookie` giúp code dễ bảo trì hơn.

## Mối liên hệ
- Các file bị ảnh hưởng: `template_fetcher.py`, `token_store.py`, `crawler.py`.
- Tác động tích cực lên toàn bộ tiến trình quét dữ liệu Facebook Group, đảm bảo tỉ lệ sống sót của các tác vụ ngầm (background jobs) và sửa triệt để lỗi không quét được ngay sau khi login.

## Rủi ro (Risks & Edge Cases)
- **Truy vấn chậm:** Việc ưu tiên gọi DB mỗi lần `_resolve_cookie` chạy (cho từng request con hoặc mỗi trang) có thể tạo ra một chút tải thêm lên Database, tuy nhiên vì bảng `requests` đã có index và truy vấn dùng `LIMIT 1` nên độ trễ là không đáng kể so với I/O mạng của Playwright/Curl.
- **Race Condition nhẹ:** Trong trường hợp token vừa hết hạn trong khi request đang gửi, hệ thống có thể cần người dùng thao tác lại để lấy cookie mới vào DB.
