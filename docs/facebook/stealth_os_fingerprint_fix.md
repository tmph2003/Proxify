# Sửa lỗi Fingerprint Mismatch trên Facebook (stealth.py)

## Tóm tắt thay đổi
1. Trong file `proxify/utils/stealth.py`, tinh chỉnh lại hàm `request()` của `StealthSessionManager`.
2. Sửa lỗi logic lấy `User-Agent` từ Header (không phân biệt hoa/thường: `User-Agent` hay `user-agent`).
3. Tự động Regex phiên bản Chrome từ chuỗi `User-Agent` và ghi đè vào `sec-ch-ua`.
4. Tự động kiểm tra hệ điều hành (Windows, macOS, Linux, Android) từ chuỗi `User-Agent` và ép kiểu `sec-ch-ua-platform` tương ứng.

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Thư viện `curl_cffi` (impersonate="chrome120") mặc định sinh ra `Sec-Ch-Ua-Platform` là `"macOS"`. Trong khi đó, `User-Agent` được lấy từ Cookie của trình duyệt người dùng lại là `Windows`. 
- **Hệ quả:** Facebook phát hiện sự mâu thuẫn giữa `User-Agent` (Windows) và `Sec-Ch-Ua-Platform` (macOS), ngay lập tức đánh dấu đây là bot và vô hiệu hóa Cookie hiện tại (Trả về lỗi `1357001` - Bắt buộc Đăng nhập).
- **Giải pháp:** Đồng bộ hóa tuyệt đối Fingerprint. Nếu người dùng dùng Chrome 131 trên Windows, `stealth.py` sẽ tự động sửa header thành `sec-ch-ua: "Chromium";v="131"` và `sec-ch-ua-platform: "Windows"`, che giấu hoàn toàn bot.

## Mối liên hệ
- File bị ảnh hưởng: `proxify/utils/stealth.py`.
- Tác động toàn cục đến tất cả các HTTP Request gửi đến Facebook GraphQL (bao gồm cả request lấy `fb_dtsg` và request Crawl thực tế).

## Rủi ro (Risks & Edge Cases)
- Logic này dựa vào Regex `Chrome/(\d+)` trong chuỗi `User-Agent`. Nếu người dùng dùng Firefox hoặc Safari, Regex có thể không bắt được version chính xác. Tuy nhiên, Facebook thường khoan dung với Firefox/Safari miễn là OS khớp.
- Đã cover các OS phổ biến (Windows, macOS, Linux, Android). Các OS hiếm gặp hơn có thể fallback về default của `curl_cffi` (macOS).
