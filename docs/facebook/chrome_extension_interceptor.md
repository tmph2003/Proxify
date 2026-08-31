# Thay đổi: Intercept GraphQL qua Chrome Extension

## Tóm tắt thay đổi
- Thêm quyền `webRequest` và service worker `background.js` vào `chrome_extension/manifest.json`.
- Tạo file `chrome_extension/background.js` để bắt gói tin GraphQL `GroupsCometFeed` và `Comment` từ trình duyệt của người dùng.
- Sửa hàm `_handle_save_cookie` trong `proxify/platforms/facebook/api.py` để nhận payload chứa `feed_template` và lưu vào `IN_MEMORY_TEMPLATES`.

## Mục đích & Ý nghĩa
Việc dùng trình duyệt ẩn danh (Playwright) trên Server bị Facebook chặn gắt gao (ra trang Checkpoint) khiến việc lấy mẫu dữ liệu (Template) bị thất bại. Giải pháp bắt trực tiếp Request GraphQL từ Chrome Extension giúp bypass hoàn toàn Playwright vì Request được gửi từ một phiên duyệt web hợp lệ của người dùng thật. Proxify chỉ việc nhận lại template chuẩn và dùng cookie để thu thập dữ liệu ngầm mà không lo bị block ở bước lấy mẫu.

## Mối liên hệ
- Liên kết chặt chẽ với logic crawl của `proxify/platforms/facebook/crawler.py`. Từ nay `crawler.py` không cần Playwright vẫn có đầy đủ `form_data` và `headers` thật.
- Thay thế hoàn toàn vai trò của `template_fetcher.py` nếu người dùng lướt feed Facebook Group bằng trình duyệt.

## Rủi ro (Risks & Edge Cases)
- **Thiếu template:** Nếu người dùng tải lại trang mà chưa cuộn xuống (scroll), Facebook chưa phát sinh API `GroupsCometFeed` thì extension sẽ không lấy được mẫu. Cần hướng dẫn người dùng phải cuộn chuột trong Group để extension bắt được request.
- **Thay đổi API:** Nếu Facebook đổi tên `fb_api_req_friendly_name` (không còn là `GroupsCometFeed` hay `CometGroup`) thì code trong background sẽ bị lọt.
- **Service Worker ngủ đông:** Trong MV3, background Service Worker có thể tự tắt sau 5 phút nếu không có hoạt động, tuy nhiên webRequest listeners vẫn được đăng ký hợp lệ.
