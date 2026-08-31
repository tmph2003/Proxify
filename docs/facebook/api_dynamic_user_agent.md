# Tối ưu hóa Fingerprint User-Agent (api.py)

## Tóm tắt thay đổi
Trong file `proxify/platforms/facebook/api.py`, hàm `_handle_facebook_crawl`:
- Lấy chính xác `User-Agent` từ trình duyệt của người dùng thông qua `request.headers.get("User-Agent")`.
- Loại bỏ giá trị `User-Agent` được hardcode cố định (`Chrome/131.0...`) thành giá trị lấy được ở trên.

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Trước đây, nếu người dùng copy/paste Cookie thủ công vào giao diện mà không dùng Extension, Backend không biết được họ đang dùng trình duyệt gì. Backend tự động gán `User-Agent` là Chrome 131. Trong khi đó, người dùng đang dùng Chrome 152. Sự bất đồng bộ này khiến Facebook (với cơ chế phát hiện bot cực gắt) cho rằng Cookie bị đánh cắp và từ chối trả về dữ liệu đăng nhập.
- **Giải pháp:** Đồng bộ hóa tự động. Bằng cách lấy đúng `User-Agent` từ HTTP Request mà người dùng gửi lên khi bấm "Bắt đầu thu thập", ta đảm bảo Fingerprint giả lập của `curl_cffi` giống hệt 100% với trình duyệt thật, đánh lừa Facebook hoàn toàn.

## Mối liên hệ
- Khắc phục lỗ hổng bảo mật khi giả lập thiết bị trong module Crawler.
- Phối hợp với `StealthSessionManager` trong `stealth.py` để tạo ra một Fingerprint bất khả xâm phạm.

## Rủi ro (Risks & Edge Cases)
Hoàn toàn an toàn và tăng cường khả năng ngụy trang cho mọi luồng crawl.
