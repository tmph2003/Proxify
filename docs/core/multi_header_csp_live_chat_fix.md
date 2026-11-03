# Sửa lỗi gộp Multi-Header (CSP / Origin-Trial) & Khôi phục YouTube Live Chat

## Tóm tắt thay đổi
1. **[`crates/proxify-core/src/proxy.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/proxify-core/src/proxy.rs)**:
   - Trong `MitmProxyServer::forward_upstream()`: Thay đổi cách lưu trữ nhiều HTTP response header trùng tên từ nối chuỗi bằng dấu phẩy `", "` sang phân tách bằng ký tự xuống dòng `'\n'`.
   - Trong `MitmProxyServer::handle_http_request()`: Khi dựng `hyper::Response` trả về cho trình duyệt, tách chuỗi theo `'\n'` và gọi `headers_mut.append(name.clone(), val)` cho từng giá trị để bảo toàn chính xác số lượng và cú pháp của các header đa bản ghi (`Content-Security-Policy`, `Content-Security-Policy-Report-Only`, `Origin-Trial`, `Vary`, `Report-To`).
2. **[`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs)**:
   - Gỡ bỏ `register_stream_exclusion` đối với `"desktop_polymer"` và `"/base.js"`, đồng thời xóa đoạn code nối `YOUTUBE_WATCHDOG_JS` vào đầu file `base.js` / `desktop_polymer.js` trong `mutate_response()`.
   - Bổ sung `*.googleapis.com` và `youtubei.googleapis.com` vào danh sách domain áp dụng `YOUTUBE_STREAM_PATHS`.
   - Trong `YOUTUBE_WATCHDOG_JS`: Thêm điều kiện loại trừ `d.closest("ytd-live-chat-frame, #chat, #chat-messages")` và siết chặt từ khóa nhận diện hộp thoại AFK (`video paused`, `continue watching`) để không ẩn nhầm các thành phần giao diện của khung trò chuyện trực tiếp.

## Mục đích & Ý nghĩa
- **Giải quyết triệt để lỗi khung Live Chat bị đen/trống khi xem YouTube Live Stream:**
  1. Trước đây, YouTube trả về 3 header `Content-Security-Policy` riêng biệt trên trang `/watch`. Việc `forward_upstream()` nối chúng bằng dấu phẩy `, ` khiến directive cuối cùng của header thứ nhất (`report-uri https://csp.withgoogle.com/csp/youtube_main/allowlist`) bị dính liền với directive đầu tiên của header thứ hai (`base-uri 'self';object-src 'none';script-src 'nonce-...'`), làm hỏng việc phân tách CSP trong trình duyệt khi khởi tạo `#chatframe` (`ytd-live-chat-frame`).
  2. Ngoài ra, việc chặn streaming đối với `base.js` và `desktop_polymer.js` khiến Proxy phải tải, giải nén và truyền lại ~3MB–8MB JavaScript không nén (`Content-Encoding` bị gỡ bỏ), gây nghẽn băng thông khởi tạo các Polymer Web Components của khung chat.
- Sau khi sửa, toàn bộ các bundle JS lớn của YouTube được stream trực tiếp ở dạng nén Brotli (`br`) nguyên bản và các header bảo mật CSP được giữ nguyên cấu trúc đa bản ghi của máy chủ Google ESF.

## Mối liên hệ
- [`crates/proxify-core/src/proxy.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/proxify-core/src/proxy.rs): Tầng hạ tầng MITM HTTP/1.1 & HTTP/2 Proxy (`forward_upstream`, `handle_http_request`).
- [`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs): Extension xử lý chặn quảng cáo, chống AFK và định tuyến luồng dữ liệu YouTube.

## Rủi ro (Risks & Edge Cases)
- **Bộ nhớ đệm (Browser Cache) của `base.js`:** Nếu trình duyệt đã lưu bản `base.js` cũ trong Disk Cache, người dùng nên nhấn `Ctrl + Shift + R` (Hard Reload) một lần trên trang YouTube Live để trình duyệt nạp lại bản HTML `/watch` và khung `#chatframe` mới nhất.
- **Tương thích với Mutator đọc Header:** Trong `HttpFlow`, nếu một `MutatorInterceptor` đọc `resp.headers.get("content-security-policy")`, chuỗi giá trị giờ đây được nối bằng `'\n'` thay vì `", "`. Regex `RE_CSP_NONCE` và `RE_CSP_TRUSTED` trong `ext-youtube` hoạt động hoàn toàn tương thích trên chuỗi đa dòng này và bảo toàn các dòng CSP còn lại khi tách lại bằng `split('\n')`.
