# Facebook Template Fetcher

## Tóm tắt thay đổi
Đã thay đổi logic cuộn (scroll) khi chờ đợi load GraphQL request của Facebook (sự kiện `GroupsCometFeed`). Cụ thể, thay vì cuộn tĩnh 2 lần (tổng 1300px), code giờ đây sử dụng một vòng lặp cuộn bất đồng bộ dưới nền (background task) thực hiện liên tục kết hợp giữa lệnh `window.scrollBy` và phím `PageDown` mỗi 0.5 giây. 

## Mục đích & Ý nghĩa
Thay đổi này nhằm khắc phục lỗi timeout 30s khi lấy mẫu template GraphQL của Facebook. Giao diện Facebook Group hiện tại có phần đầu (cover, pinned post, bio) rất dài, khiến khoảng cách cuộn 1300px không đủ để kích hoạt cơ chế Lazy Loading (IntersectionObserver) để gọi thêm bài viết. Vòng lặp liên tục đảm bảo trang sẽ được cuộn liên tiếp mượt mà cho đến khi bắt được request hoặc hết thời gian tối đa.

## Mối liên hệ
Thay đổi này nằm trong file `proxify/platforms/facebook/template_fetcher.py`. Nó ảnh hưởng trực tiếp đến khả năng thành công của quá trình lấy dữ liệu mẫu ban đầu, từ đó quyết định xem toàn bộ crawler (trong `proxify.facebook.crawler` / `api.py`) có thể hoạt động hay không.

## Rủi ro (Risks & Edge Cases)
- **Playwright Context Error:** Vì đây là một background task, nếu trình duyệt hoặc tab bị đóng đột ngột (ví dụ do timeout), task có thể cố gắng truy cập lại đối tượng `page` đã bị hủy. (Đã xử lý bằng cách bọc `try/except` trong task và hủy task bằng `scroll_task.cancel()` một cách an toàn trong khối `finally`/`except`).
- **Phát hiện bot (Anti-bot):** Hành động cuộn quá đều đặn (mỗi 0.5s) có thể bị một hệ thống anti-bot cực kỳ nhạy cảm phát hiện, tuy nhiên trong trường hợp này việc lấy mẫu chỉ diễn ra một lần ở một Playwright profile sạch nên rủi ro là cực kỳ thấp.
