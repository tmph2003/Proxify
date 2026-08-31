# Báo cáo Cập nhật: Sửa lỗi "Cookies đã hết hạn" (Error 1357001)

## Tóm tắt thay đổi
Đã thực hiện 3 sửa đổi chính nhằm khắc phục lỗi crawler không nhận cookie mới và bị chặn bởi cơ chế chống bot của Facebook:
1. Đảo ngược độ ưu tiên nạp Cookie trong `crawler.py`.
2. Thay thế `aiohttp` bằng thư viện `StealthSessionManager` (ẩn danh JA3/TLS) trong `auth_fetcher.py`.
3. Viết lại logic bóc tách token `fb_dtsg` và `lsd` để hỗ trợ trích xuất trực tiếp từ trang chủ `www.facebook.com` (React SPA) thay vì trang `mbasic`.

## Mục đích & Ý nghĩa
- **Giải quyết vấn đề vòng lặp báo lỗi:** Trước đây, mặc dù người dùng đã dán cookie mới, Proxify vẫn dùng lại cookie cũ lưu trong RAM từ Template GraphQL. Việc cập nhật ưu tiên cho phép người dùng ghi đè (override) ngay lập tức bằng cookie tươi mà không cần khởi động lại.
- **Tránh Anti-Bot:** Facebook đã bắt đầu chặn hoặc chuyển hướng các request gọi vào `mbasic.facebook.com` bằng HTTP Client thông thường (aiohttp) vì dễ nhận diện. Chuyển sang `StealthSessionManager` giúp giả lập handshake TLS giống hệt trình duyệt thật, tránh bị block/checkpoint oan.
- **Lấy Token chính xác:** Việc trích xuất dữ liệu từ `DTSGInitialData` trên trang web mới đảm bảo crawler luôn có token bảo mật hợp lệ để gửi kèm theo yêu cầu GraphQL.

## Mối liên hệ
Những thay đổi này tác động trực tiếp đến module Facebook Crawler:
- **`proxify/platforms/facebook/crawler.py`**: Phương thức `_resolve_cookie` được viết lại.
- **`proxify/platforms/facebook/auth_fetcher.py`**: Logic `fetch_fb_auth_tokens` được viết lại hoàn toàn.
- **`proxify/platforms/facebook/api.py`**: API lưu trữ cookie không thay đổi logic nhưng giờ đây được hưởng lợi nhờ việc crawler tự động ưu tiên cookie do người dùng cung cấp.

## Rủi ro (Risks & Edge Cases)
1. **Lỗi Parsing Regex (Cao):** Do React SPA của Facebook thường xuyên thay đổi cấu trúc mã nguồn, Regex để tìm `"DTSGInitialData"` có thể bị hỏng trong tương lai. Nếu điều này xảy ra, crawler sẽ không bóc tách được `fb_dtsg` và cần phải điều chỉnh Regex.
2. **Khác biệt Headers / User-Agent (Vừa):** Hiện tại code đã cố gắng bám sát `user-agent` mà người dùng truyền vào (hoặc mặc định của extension). Nếu người dùng dùng cookie từ trình duyệt Safari/Mac nhưng `StealthSessionManager` mô phỏng Windows/Chrome, Facebook có thể đánh dấu phiên đăng nhập là bất thường và văng Checkpoint.
3. **Cookie định dạng sai:** Đã thêm check chứa `c_user=` và `xs=`. Tuy nhiên, nếu cookie bị thiếu các phần tử liên quan đến Datar (datr, fr, v.v.), có thể request lấy token ban đầu vẫn bị chặn. 
