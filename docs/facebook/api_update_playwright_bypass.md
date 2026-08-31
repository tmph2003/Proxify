# Cập nhật API Facebook (api.py)

## Tóm tắt thay đổi
Sửa đổi hàm `_handle_facebook_crawl` để hoàn toàn bỏ qua việc gọi tiến trình `template_fetcher` (Playwright) nếu người dùng đã có sẵn Template trong RAM (`IN_MEMORY_TEMPLATES.get("feed")`) **HOẶC** người dùng đã cung cấp Cookie thủ công (`cookie`).

## Mục đích & Ý nghĩa
Facebook hiện đang chặn rất mạnh các yêu cầu khởi tạo từ Playwright (headless browser), khiến hệ thống liên tục văng lỗi "Cookie Facebook đã hết hạn" (bị đẩy về trang đăng nhập) mỗi khi khởi động lại backend và bị mất template trong RAM.
Việc sửa đổi này giúp ưu tiên sử dụng `start_crawler` với template lưu trữ cũ (fallback) và cookie mới, tránh phụ thuộc vào Playwright.

## Mối liên hệ
- File bị ảnh hưởng: `proxify/platforms/facebook/api.py`.
- Liên quan trực tiếp tới: `proxify/platforms/facebook/crawler.py` (nơi xử lý fallback tải template từ file disk nếu RAM trống).

## Rủi ro (Risks & Edge Cases)
- Nếu cấu trúc GraphQL của Facebook thay đổi (template cũ trên disk không còn dùng được) VÀ người dùng chỉ nhập cookie thủ công (không dùng Extension để lấy template mới), crawler sẽ gặp lỗi parse dữ liệu thay vì báo lỗi cookie.
- Giải pháp: Khuyến khích người dùng luôn dùng Extension để lấy cả Cookie và Template.
