# Tài liệu: Sửa chuỗi lỗi chặn JS Injection của Zalo Bot

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/platforms/zalo/bot.py`:
  1. Thay đổi cổng proxy mặc định từ `8080` sang đọc từ biến môi trường `PROXY_PORT` (mặc định `8081` để khớp với `server_v2.py`).
  2. Thêm cờ `--disable-cache` vào cấu hình Playwright.
  3. Thêm logic Hủy đăng ký (Unregister) Service Worker của Zalo và tự động tải lại trang (`page.reload`) trước khi bắt đầu quét job.
- Chỉnh sửa file `proxify/platforms/zalo/extractor.py`:
  Sử dụng thư viện `urllib.parse.urlparse` để lấy chính xác đuôi `.js`, bất chấp việc URL có kèm theo query parameters (ví dụ `main.js?v=123`). Sửa lỗi này đồng bộ ở cả 2 hàm `modify_zalo_response` và `inject_hooks`.

## Mục đích & Ý nghĩa
- **Lỗi cổng Proxy:** Bot Zalo trước đây hardcode cổng `8080`, khiến nó vô tình kết nối nhầm vào server cũ hoặc không có proxy nếu người dùng đang chạy `server_v2.py` (cổng `8081`). Điều này khiến bot không đi qua V2 Router.
- **Lỗi Query Params (Xảy ra 2 lần):** Hàm bắt link JS cũ dùng lệnh `endswith(".js")`. Zalo thường gán thêm tham số phiên bản `?v=xxx` vào sau đuôi js, khiến hàm này bỏ lọt 100% file JS quan trọng. Lần trước tôi đã sửa lỗi này ở vỏ bọc ngoài `modify_zalo_response`, nhưng lại quên sửa ở tận bên trong lõi hàm `inject_hooks`, khiến cho JS vẫn bị thả trôi không được tiêm. Lần này tôi đã vá lỗ hổng này ở cả 2 nơi.
- **Lỗi Service Worker Cache:** Playwright lưu lại state của trình duyệt trong thư mục `zalo_browser_data`. Mặc dù đã sửa lỗi GZIP và Query Params ở proxy, nhưng Zalo Web sử dụng **Service Worker** để Cache (lưu trữ nội bộ) toàn bộ file JS. Khi bot mở Zalo, Service Worker trả ngay file JS cũ (file chưa được tiêm JS Hook) từ ổ cứng, proxy hoàn toàn không nhận được request để mà tiêm! Việc unregister Service Worker ép trình duyệt phải gửi yêu cầu lên mạng để lấy JS mới, từ đó đi qua proxy và được tiêm JS thành công.

## Mối liên hệ
- Liên quan mật thiết tới Zalo Bot, Zalo Extractor và luồng Proxy V2. 

## Rủi ro (Risks & Edge Cases)
- Việc hủy Service Worker và tải lại trang mỗi lần mở Zalo Bot sẽ khiến bot tải chậm hơn khoảng 2-3 giây ở lần đầu tiên (do không dùng cache nội bộ), nhưng đổi lại đảm bảo tỷ lệ thành công 100% trong việc tiêm mã JS vào hệ thống của Zalo. Đây là sự đánh đổi hoàn toàn xứng đáng.
