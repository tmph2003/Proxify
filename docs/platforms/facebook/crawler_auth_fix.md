# Tài liệu: Xử lý lỗi xác thực Facebook (Error 1357001) trong Crawler

## 1. Tóm tắt thay đổi
1. **Sửa lỗi Parse Lỗi GraphQL**: Thêm hàm `.strip()` vào `resp_text` trong file `proxify/platforms/facebook/crawler.py` trước khi kiểm tra `startswith("for (;;);")` nhằm loại bỏ khoảng trắng/newline thừa (nguyên nhân khiến logic bắt lỗi cũ bị trượt).
2. **Sửa lỗi không nhận diện Cookie mới khi Refresh**: Chuyển đổi toán tử `LIKE '%cookie%'` thành `ILIKE '%cookie%'` (không phân biệt hoa/thường) trong các file `template_fetcher.py` và `token_store.py` khi truy vấn database `public.requests`.
3. **Đồng bộ User-Agent cho Playwright**: Trích xuất `user-agent` thật của người dùng từ database (cùng dòng với cookie) thay vì dùng chuỗi cứng `Chrome/152.0...` rồi bơm (inject) vào context của Playwright trong `template_fetcher.py`.
4. **Dừng ngay khi phát hiện Cookie hết hạn**: Nếu Template Fetcher báo "redirected to login", hệ thống **dừng ngay** và hiện thông báo lỗi rõ ràng thay vì tiếp tục chạy Crawler với cookie cũ vô nghĩa. Áp dụng cả 2 file: `api.py` và `plugins/facebook.py`.
5. **Cập nhật Chrome Extension**: Sửa lỗi Extension chỉ bắn mỗi Cookie mà không kèm User-Agent. Extension giờ sẽ thu thập `navigator.userAgent` và gửi kèm vào payload để `template_fetcher.py` có thể dùng đóng giả chính xác trình duyệt của user, chống bị Facebook chặn.
6. **Bypass hoàn toàn Playwright (Ultimate Fix)**: Cấp quyền `scripting` và `activeTab` cho Chrome Extension để chèn mã trực tiếp vào tab Facebook của người dùng, lấy chính xác token `fb_dtsg` và `lsd` từ biến `require("DTSGInitialData")`. Các token này được nạp thẳng vào `api.py`. Nhờ đó, Proxify **bỏ qua hoàn toàn bước dùng Playwright** (vốn rất dễ bị Facebook nhận diện là bot và bắt đăng nhập lại), giải quyết triệt để lỗi "đã đăng nhập nhưng crawler vẫn báo lỗi".

## 2. Mục đích & Ý nghĩa
- **Khắc phục triệt để lỗi Silent Failure**: Khi cookie Facebook hết hạn, API GraphQL vẫn trả về mã 200 OK nhưng chứa lỗi. Logic cắt chuỗi JSON hiện đã ổn định hơn nhờ loại bỏ các khoảng trắng/xuống dòng thừa thãi, giúp hiển thị thông báo lỗi chính xác ra UI thay vì kết thúc im lặng.
- **Sửa lỗi Refresh Cookie nhưng vẫn báo hết hạn**: Dùng `ILIKE` giúp hệ thống luôn nhận ra Header `Cookie` (chữ C viết hoa) của trình duyệt.
- **Chống bị Facebook đá ra trang Login (Session Hijacking check)**: Dù đã có cookie mới và xịn, Playwright (dùng headless) vẫn bị Facebook điều hướng về `/login`. Nguyên nhân là Facebook kiểm tra thấy **User-Agent lúc đăng nhập khác với User-Agent hiện tại** (vì trước đó Playwright bị code cứng User-Agent `Chrome/152.0...` không khớp với trình duyệt thật của người dùng). Việc đồng bộ User-Agent giúp Playwright đóng giả hoàn hảo trình duyệt của bạn, vượt qua chốt chặn bảo mật của Facebook. Áp dụng cho cả cookie lấy từ DB lẫn cookie nạp qua **Chrome Extension**.
- **Loại bỏ nguy cơ bị khoá/checkpoint do Playwright (Bot Detection)**: Dù Playwright có cookie và User-Agent xịn, Facebook vẫn có thể nhận ra Headless Chromium dựa trên Canvas, WebGL, và các thông số fingerprint khác, dẫn đến việc huỷ cookie (ép đăng nhập lại cả trình duyệt gốc). Bằng cách cho Extension bắt luôn `fb_dtsg` từ tab thật, Proxify không cần khởi động Playwright nữa mà gọi thẳng `curl_cffi` (giả lập TLS siêu an toàn).
- **Fail-fast thay vì Fail-silent**: Khi Template Fetcher phát hiện bị redirect về trang đăng nhập, hệ thống dừng ngay lập tức và hiển thị hướng dẫn cụ thể cho người dùng (lướt qua proxy hoặc dán cookie thủ công), thay vì tiếp tục chạy crawler với cookie cũ rồi thất bại âm thầm.

## 3. Mối liên hệ
- **Module ảnh hưởng trực tiếp**: 
  - `proxify/platforms/facebook/crawler.py` (hàm `_execute_crawl_group_feed`)
  - `proxify/platforms/facebook/template_fetcher.py` (hàm `_get_fb_cookies_from_db`, `fetch_fresh_template`)
  - `proxify/platforms/facebook/token_store.py`
  - `proxify/platforms/facebook/api.py` (hàm `_crawl_with_fresh_template`, `_handle_save_cookie`)
  - `proxify/plugins/facebook.py` (hàm `_crawl_with_fresh_template`, `_handle_save_cookie`)
  - `chrome_extension/popup.js`
- **Giao diện (Frontend)**: Nhận thông báo lỗi rõ ràng kèm hướng dẫn xử lý thay vì kết thúc im lặng. Tích hợp liền mạch với Chrome Extension.

## 4. Rủi ro (Risks & Edge Cases)
- **Định dạng JSON của Facebook**: Nếu Facebook bỏ chuỗi `for (;;);`, logic bắt lỗi auth sẽ thất bại.
- **Trường hợp lỗi mạng/Parse Error**: Khối lệnh bắt lỗi JSON vẫn được bọc trong `try-except`, nếu có lỗi phát sinh nó sẽ tự bỏ qua, không gây crash crawler.
- **String matching "redirected to login"**: Logic abort dựa vào chuỗi text trong stderr. Nếu ai đó sửa lại message trong template_fetcher mà không cập nhật điều kiện kiểm tra thì sẽ mất tính năng fail-fast.
