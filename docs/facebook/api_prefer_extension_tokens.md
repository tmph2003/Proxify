# Tối ưu hóa việc sử dụng Token từ Extension (api.py)

## Tóm tắt thay đổi
Trong file `proxify/platforms/facebook/api.py` (hàm `_handle_facebook_crawl`):
Thêm logic kiểm tra: Nếu trong `IN_MEMORY_COOKIES` đã có sẵn `fb_dtsg` và `lsd` (được gửi lên từ Proxify Extension) và `fb_dtsg` là token hợp lệ (không bắt đầu bằng chữ `AdQ` của tài khoản khách), hệ thống sẽ **sử dụng luôn token này** thay vì gọi hàm `_update_tokens_via_http` để tải lại trang chủ Facebook.

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Trước đây, mặc dù người dùng dùng Extension lấy được token `fb_dtsg` hoàn toàn hợp lệ (ví dụ: `NAfxe2...`), backend vẫn bỏ qua và gọi hàm fetch HTTP lại từ đầu. Việc fetch HTTP bằng curl_cffi đôi khi bị Facebook chặn hoặc đánh dấu là truy cập lạ (vì IP / session check khắt khe), trả về trang chủ chưa đăng nhập kèm token giả `AdQ...`. Sau đó backend lại lấy token giả này ghi đè lên token thật của Extension, dẫn đến lỗi 1357001 khi crawl GraphQL.
- **Giải pháp:** Tôn trọng dữ liệu từ Extension. Token Extension lấy trực tiếp từ trình duyệt của người dùng là xịn nhất và không bao giờ bị Facebook chặn. Nếu có sẵn, ta dùng luôn, bỏ qua bước fetch HTTP đầy rủi ro.

## Mối liên hệ
- File sửa đổi: `proxify/platforms/facebook/api.py`.
- Tác động: Khắc phục triệt để lỗi 1357001 cho những người dùng sử dụng Extension.

## Rủi ro (Risks & Edge Cases)
- Trong trường hợp người dùng không dùng Extension mà tự copy Cookie dán vào UI, hàm vẫn sẽ chạy HTTP fetch bình thường (fallback fallback).
