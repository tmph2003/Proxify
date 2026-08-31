# Cập nhật logic truyền Cookie cho Playwright Fetcher (api.py)

## Tóm tắt thay đổi
1. Gỡ bỏ logic bypass Playwright (đã thêm ở lần sửa trước) trong hàm `_handle_crawl_posts`.
2. Khi khởi chạy tiến trình con chạy Playwright thông qua `subprocess.run`, hệ thống giờ đây sẽ sao chép môi trường (`os.environ.copy()`) và gắn thêm biến `PROXIFY_FB_COOKIE` (và `PROXIFY_FB_UA` nếu có).

## Mục đích & Ý nghĩa
- **Vấn đề trước đây:** Người dùng đã dán Cookie vào giao diện UI (được lưu tại `localStorage` và gửi lên qua API). Tuy nhiên, backend lại khởi tạo một tiến trình Playwright ẩn (để lấy mã `fb_dtsg` và `lsd`) mà **không hề** truyền cookie mới này cho tiến trình đó. Hậu quả là Playwright dùng cookie cũ/trống trong DB, bị Facebook chặn và chuyển hướng về trang đăng nhập, gây ra lỗi "Cookie đã hết hạn". Khi tôi thử bypass Playwright, hệ thống lại dùng mã `fb_dtsg` tĩnh cũ, dẫn đến mã lỗi GraphQL `1357001` (lỗi xác thực).
- **Giải pháp:** Truyền trực tiếp Cookie người dùng vừa nhập vào làm biến môi trường cho Playwright (`PROXIFY_FB_COOKIE`). Playwright sẽ đăng nhập thành công bằng cookie đó, lấy được mã `fb_dtsg` mới và tự động tạo request GraphQL hợp lệ mà không bị văng lỗi.

## Mối liên hệ
- File bị ảnh hưởng: `proxify/platforms/facebook/api.py`.
- Liên quan tới: `proxify/platforms/facebook/template_fetcher.py` (nơi ưu tiên đọc biến môi trường `PROXIFY_FB_COOKIE` trước khi đọc DB).

## Rủi ro (Risks & Edge Cases)
- Playwright tốn thời gian khởi động (có thể mất 5-10 giây để lấy template). Tuy nhiên, đây là cách duy nhất đảm bảo mã `fb_dtsg` luôn tươi và khớp hoàn toàn với cookie, giải quyết triệt để lỗi 1357001.
