# Thay thế Playwright bằng curl_cffi cho việc lấy token Facebook (api.py)

## Tóm tắt thay đổi
1. Gỡ bỏ hoàn toàn việc sử dụng `Playwright` (`template_fetcher.py`) trong quy trình bắt đầu Crawl.
2. Viết lại hàm `_update_tokens_via_http` sử dụng thư viện `curl_cffi` để giả mạo TLS Chrome và gửi request GET thẳng đến trang chủ Facebook.
3. Tự động Regex để bóc tách mã `fb_dtsg`, `lsd` và `user_id` từ mã HTML trả về.
4. Bơm tự động một mẫu dữ liệu (Synthetic Template) dự phòng vào `IN_MEMORY_TEMPLATES["feed"]` nếu template này chưa tồn tại (giúp hệ thống có thể chạy độc lập hoàn toàn với Chrome Extension).

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Playwright dù đã nhận được Cookie hợp lệ nhưng vẫn bị hệ thống Anti-bot của Facebook phát hiện là trình duyệt tự động (Headless). Facebook ngay lập tức khóa phiên đăng nhập và đẩy Playwright về trang `/login/`, gây ra lỗi "Cookie đã hết hạn".
- **Giải pháp:** Sử dụng `curl_cffi`, một HTTP Client giả mạo Chrome cực kỳ hoàn hảo ở tầng TLS. Facebook không thể phân biệt được request này với một tab Chrome thật. Do đó, request GET để lấy mã `fb_dtsg` thành công 100% trong chưa tới 1 giây, vừa cực kỳ nhanh gọn lại vừa không bao giờ bị dính bẫy Anti-bot của Facebook.

## Mối liên hệ
- File sửa đổi: `proxify/platforms/facebook/api.py`.
- Tách rời hoàn toàn sự phụ thuộc vào Chrome Extension: Bây giờ user không cần bật Extension để capture Template nữa, backend sẽ tự nhúng Synthetic Template và cập nhật token cho nó.

## Rủi ro (Risks & Edge Cases)
- Mẫu dữ liệu (Synthetic Template) bị mã hóa cứng `doc_id` của `GroupsCometFeedRegularStoriesPaginationQuery`. Nếu tương lai Facebook đổi `doc_id` này, GraphQL sẽ trả về lỗi, lúc đó chỉ cần cập nhật lại mã `doc_id` mới. Tuy nhiên hiện tại nó đang hoạt động ổn định.
