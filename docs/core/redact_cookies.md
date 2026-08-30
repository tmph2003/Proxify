# Không lưu Cookies ở Database

## Tóm tắt thay đổi
Đã sửa đổi module `DatabaseWriter` trong `proxify/core/listeners.py` để chủ động gạt bỏ (redact) các thông tin nhạy cảm trước khi lưu vào Database.
Cụ thể:
- Lọc `request.headers`: Nếu có key là `cookie` (hoặc `Cookie`), giá trị sẽ bị thay thế bằng `[REDACTED]`.
- Lọc `response.headers`: Nếu có key là `set-cookie` (hoặc `Set-Cookie`), giá trị cũng bị thay thế bằng `[REDACTED]`.

## Mục đích & Ý nghĩa
Sự thay đổi này được thực hiện theo yêu cầu "tuyệt đối không lưu cookies ở database" của người dùng, nhằm bảo vệ quyền riêng tư và bảo mật dữ liệu phiên đăng nhập. Nó đảm bảo kể cả khi database bị lộ, kẻ tấn công cũng không thể lấy được cookie thật của người dùng để chiếm quyền tài khoản Facebook, Zalo, hay bất kỳ hệ thống nào khác đi qua proxy.

## Mối liên hệ
Thay đổi ở `proxify/core/listeners.py` (nơi hứng luồng dữ liệu từ Mitmproxy). Do việc không lưu cookie vào DB, tính năng "Tự động lấy cookie từ database" (ví dụ: hàm `get_cookies_and_ua_from_db` trong `proxify/platforms/facebook/token_store.py` vừa được fix trước đó) sẽ không còn hoạt động. Hệ thống Crawler giờ đây bắt buộc phải lấy cookie từ file `tokens.json` do Template Fetcher tự tạo, hoặc từ cookie do người dùng cung cấp qua UI/Biến môi trường.

## Rủi ro (Risks & Edge Cases)
- **Tính năng Fallback bị vô hiệu hoá:** Tính năng tự động fallback cookie khi crawl bị hỏng (Error 1357001) sẽ mất hiệu lực. Người dùng sẽ phải tự thao tác trên giao diện để cập nhật cookie hoặc chạy lại công cụ `Template Fetcher`.
- Việc mask cookie hiện tại dùng list comprehension tạo ra một bản copy dict, điều này hoàn toàn an toàn và không thay đổi logic luồng request/response thực tế của Mitmproxy (không làm hỏng request gửi đi).
