# Tóm tắt cập nhật hệ thống: Tối ưu Docker và Tích hợp CloakBrowser

## 1. Tóm tắt thay đổi
- Sửa lỗi không parse được `multipart/form-data` trong `proxify/platforms/facebook/template_fetcher.py` khi Facebook đổi định dạng Request GraphQL.
- Đổi `headless=False` thành `headless=True` trong các file tự động hóa (`template_fetcher.py` và `zalo/bot.py`) để tránh lỗi crash khi chạy bên trong Docker container (môi trường không có màn hình X11).
- Tối ưu hóa lại cấu trúc `Dockerfile` bằng cách đẩy các bước cài đặt tốn thời gian (OS dependencies của Playwright) lên trước lệnh `COPY . .` nhằm tận dụng tối đa Docker Layer Caching.
- Đưa mã nguồn `CloakBrowser` vào trong build context của Docker và loại bỏ lệnh `pip install` ở runtime trong `docker-compose.yml` để tăng tốc khởi động container.

## 2. Mục đích & Ý nghĩa
- Đảm bảo luồng lấy template của Facebook Extractor tự động hóa thông suốt.
- Tăng tốc độ vòng lặp phát triển (Local Development) bằng cách loại bỏ thời gian build và start container dài vô lý. Container hiện tại chỉ mất < 1 giây để khởi động lại thay vì 15 giây.
- Ổn định hóa hệ thống khi chạy qua Docker.

## 3. Mối liên hệ
- Ảnh hưởng đến `docker-compose.yml`, `Dockerfile`.
- Các file Python: `proxify/plugins/facebook.py`, `proxify/platforms/facebook/api.py`, `proxify/platforms/facebook/template_fetcher.py`, `proxify/platforms/zalo/bot.py`.

## 4. Rủi ro (Risks & Edge Cases)
- Do `CloakBrowser` được mount qua Docker Volumes ở Local Dev, nếu xóa thư mục này bên ngoài máy host, container có thể không start được.
- Nếu Facebook tiếp tục thay đổi cấu trúc `multipart/form-data` hoặc đổi tên trường `fb_api_req_friendly_name`, biểu thức chính quy (Regex) bóc tách payload có thể bị lệch và cần cập nhật lại.
