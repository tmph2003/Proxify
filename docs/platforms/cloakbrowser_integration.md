# Tích hợp CloakBrowser (Stealth Engine)

## 1. Tóm tắt thay đổi
- Đã thay thế trình duyệt Chromium mặc định của thư viện `playwright` bằng trình duyệt ảo hóa `CloakBrowser` trong hai module chính:
  - `proxify/platforms/zalo/bot.py`
  - `proxify/platforms/facebook/template_fetcher.py`
- Thay thế các lời gọi `async_playwright().chromium.launch(...)` bằng các hàm `launch_async` và `launch_persistent_context_async` từ package `cloakbrowser`.

## 2. Mục đích & Ý nghĩa
- **Vượt hệ thống chống Bot (Anti-bot Bypass):** Playwright mặc định rất dễ bị nhận diện bởi Cloudflare hoặc reCAPTCHA do rò rỉ thông số `navigator.webdriver` hoặc vân tay TLS. `CloakBrowser` là một phiên bản Chromium được can thiệp (patch) ở tầng mã nguồn C++ để giả lập 100% giống trình duyệt thật.
- **Tăng tính ẩn danh:** Việc nhúng CloakBrowser giúp các Bot tự động (như đi bắt Cookie FB hoặc quét Group Zalo) không bị chặn hoặc yêu cầu giải mã Captcha liên tục.

## 3. Mối liên hệ
- Ảnh hưởng trực tiếp đến `zalo.bot` (tiến trình chạy ngầm quét thành viên Zalo).
- Ảnh hưởng trực tiếp đến `facebook.template_fetcher` (tiến trình tự động sinh bộ Template cho GraphQL FB).
- Hai module này chia sẻ chung thư viện `CloakBrowser`, yêu cầu hệ thống phải cài đặt package này qua lệnh `pip install -e ../CloakBrowser`.

## 4. Rủi ro (Risks & Edge Cases)
- **Tải tệp lớn ở lần chạy đầu:** `CloakBrowser` yêu cầu tải một bản binary Chromium tùy chỉnh nặng ~535MB ở lần chạy đầu tiên. Nếu đường truyền có vấn đề, bot sẽ không khởi động được. (Đã xử lý tạm thời bằng cách thêm `verify=False` vào mã tải xuống để tránh lỗi chứng chỉ SSL do chạy qua Proxy).
- **Tràn RAM/Ổ cứng:** Việc tải nhiều binary và lưu cache (user_data_dir) nếu không được dọn dẹp thường xuyên có thể gây phình to dung lượng thư mục `zalo_browser_data`.
- **Tương thích:** Dù `CloakBrowser` tuyên bố "drop-in replacement" với Playwright, một số flag launch nâng cao có thể không hoạt động hoặc xung đột với bản vá của họ. Cần theo dõi hành vi của Bot sau khi tích hợp.
