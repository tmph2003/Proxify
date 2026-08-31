# Fix lỗi Cookie hết hạn 1357001 bằng Script get fb_dtsg tự động

## Tóm tắt thay đổi
- Tạo file `proxify/platforms/facebook/auth_fetcher.py` chứa hàm `fetch_fb_auth_tokens`. Hàm này sử dụng `curl_cffi` để mạo danh Chrome 120, gửi HTTP GET request lên `https://mbasic.facebook.com/` và trích xuất `fb_dtsg`, `lsd`.
- Sửa lại `plugins/facebook.py` và `platforms/facebook/api.py` để tích hợp `auth_fetcher`: Nếu người dùng paste cookie vào UI, crawler sẽ TỰ ĐỘNG gọi `auth_fetcher` để kiểm tra cookie và lấy `fb_dtsg` mới tương ứng với cookie đó.

## Mục đích & Ý nghĩa
- Khắc phục lỗi Facebook trả về mã `1357001` (Cookie không hợp lệ hoặc hết hạn). Lỗi này thường xảy ra khi người dùng paste một Cookie mới lên UI, nhưng crawler vẫn giữ `fb_dtsg` cũ từ `IN_MEMORY_TEMPLATES`. Facebook yêu cầu `cookie` và `fb_dtsg` phải hoàn toàn khớp với cùng một phiên đăng nhập.
- Loại bỏ hoàn toàn sự phụ thuộc vào Playwright (việc dùng Playwright để lấy token gây treo máy và lỗi quá timeout). Giờ đây việc lấy token diễn ra cực nhanh bằng HTTP request.
- Nếu cookie thực sự hết hạn (Facebook redirect về trang `/login`), hệ thống sẽ phát hiện ngay lập tức và báo "Cookie đã bị Facebook từ chối" thay vì bắt đầu crawl rồi bị văng lỗi.

## Mối liên hệ
- File mới: `proxify/platforms/facebook/auth_fetcher.py`
- Tích hợp vào: `_crawl_with_fresh_template` trong cả 2 file API (`platforms/facebook/api.py` và `plugins/facebook.py`).

## Rủi ro (Risks & Edge Cases)
- `curl_cffi` mạo danh Chrome 120 có thể bị Facebook chặn nếu gửi quá nhiều request trong thời gian ngắn (ít xảy ra vì chỉ gọi 1 lần khi bắt đầu crawl).
- Nếu Facebook cập nhật giao diện `mbasic.facebook.com`, regex trích xuất `fb_dtsg` có thể thất bại. Đã có fallback sang `www.facebook.com` để tăng tính ổn định.
