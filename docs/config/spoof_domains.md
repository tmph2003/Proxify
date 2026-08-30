# Cập nhật SPOOF_DOMAINS — Thêm domain Zalo

## Tóm tắt thay đổi
Thêm các domain Zalo (`zalo.me`, `chat.zalo.me`, `zalo.vn`, `zalopay.vn`, `zaloapp.com`) vào biến `SPOOF_DOMAINS` trong cả file `.env` và `docker-compose.yml`.

## Mục đích & Ý nghĩa
- Zalo đang phát hiện TLS fingerprint bất thường từ Mitmproxy (dùng Python TLS mặc định) và bắt người dùng nhập captcha.
- Khi thêm Zalo vào `SPOOF_DOMAINS`, plugin `TLSSpooferPlugin` sẽ dùng `curl_cffi` để giả lập TLS handshake giống hệt trình duyệt Chrome thật.
- Zalo Server sẽ thấy TLS fingerprint (JA3) giống Chrome → không trigger captcha nữa.
- Dữ liệu mã hóa tầng ứng dụng (E2EE) vẫn được `curl_cffi` truyền nguyên xi về cho trình duyệt để giải mã bình thường.

## Mối liên hệ
- **`.env`** (dòng 8): Biến `SPOOF_DOMAINS` được đọc bởi `TLSSpooferPlugin` trong `proxify/plugins/tls_spoofer.py`.
- **`docker-compose.yml`** (dòng 22): Giá trị mặc định cho biến `SPOOF_DOMAINS` khi chạy trong Docker container.
- **`proxify/plugins/tls_spoofer.py`**: Plugin đọc `SPOOF_DOMAINS` từ env, so khớp domain request, và dùng `curl_cffi` để thay thế TLS connection.
- **`proxify/platforms/zalo/bot.py`**: Bot Playwright kết nối Zalo Web qua MITM proxy — giờ các request của Bot sẽ được spoof TLS.

## Rủi ro (Risks & Edge Cases)
- **Hiệu năng:** Thêm domain vào `SPOOF_DOMAINS` nghĩa là mọi request tới Zalo đều đi qua `curl_cffi` thay vì đường Mitmproxy mặc định. Tuy nhiên overhead không đáng kể.
- **WebSocket:** Code `tls_spoofer.py` đã bỏ qua WebSocket requests (dòng 42-46), nên chat real-time của Zalo sẽ không bị ảnh hưởng.
- **Tương thích JS Hook:** JS Hook inject vào response vẫn hoạt động bình thường vì `ZaloPlugin.on_response()` chạy SAU khi `TLSSpooferPlugin.on_request()` đã set `flow.response`. Tuy nhiên cần lưu ý: khi `tls_spoofer` đã tạo `flow.response` trong `on_request`, Mitmproxy sẽ không gửi request thật đi nữa → `on_response` của ZaloPlugin cũng sẽ được gọi với response do `curl_cffi` tạo ra → JS injection vẫn hoạt động.
