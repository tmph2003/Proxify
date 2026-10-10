# Tài liệu Kỹ thuật: Bổ sung Bypass CDN `c.youtube.com` & Tối ưu Guardrail Script Watchdog YouTube

## 1. Tóm tắt thay đổi
- **Hạ tầng Proxy & Bypass CDN YouTube:**
  - Bổ sung tên miền `c.youtube.com` (và wildcard `*.c.youtube.com`) vào danh sách `IGNORE_HOSTS` trong [docker-compose.yml](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml) và [backend/proxify/server.py](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py).
  - Cập nhật Windows `ProxyOverride` tại `HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings` bổ sung `*.c.youtube.com` và `c.youtube.com`, đồng bộ qua `InternetSetOption` và WinHTTP (`netsh winhttp import proxy source=ie`).
- **Lõi Extension YouTube ([backend/extensions/youtube/](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/extensions/youtube/)):**
  - Trong `extension.py`: Đăng ký bổ sung `"c.youtube.com"` vào danh sách stream domains thông qua `context.register_stream_domains(["googlevideo.com", "c.youtube.com"])`.
  - Trong [backend/proxify/utils/youtube_utils.py](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/utils/youtube_utils.py):
    - Cập nhật hàm `is_youtube_ad_request` để miễn trừ tuyệt đối cả `googlevideo.com` lẫn `c.youtube.com` khỏi bộ lọc chặn quảng cáo 204.
    - Bổ sung kiểm tra an toàn `v.readyState >= 2` trong hàm `resumeVideo()` của đoạn mã in-page Anti-AFK Watchdog trước khi gọi `video.play()`.

---

## 2. Mục đích & Ý nghĩa
- **Hiện tượng lỗi:** Người dùng mở video/live stream YouTube (ví dụ `youtube.com/watch?v=DJFqH13qTfE`), trình phát HTML5 hiển thị màn hình đen kèm thông báo:
  > *"Đã xảy ra lỗi. Vui lòng thử lại sau. (Mã lượt phát: HHKlbGesJ4_sB2im)"*
- **Nguyên nhân gốc rễ:**
  1. **Nghẽn/Ngắt kết nối cụm CDN Video `c.youtube.com`:** Ngoài `googlevideo.com`, YouTube sử dụng mạng lưới Google Global Cache (GGC) với dải subdomain dạng `rr*---sn-*.c.youtube.com` (như `rr4---sn-u1npoc-54.c.youtube.com`) để phân phát video stream và live segment. Do thiếu `c.youtube.com` trong danh sách bypass, các kết nối thăm dò `/generate_204` và chunk stream bị Mitmproxy can thiệp giải mã TLS, dẫn đến việc máy chủ GGC ngắt kết nối (`server disconnect`), gây lỗi MediaSource mạng (`MEDIA_ERR_NETWORK`) trên trình phát.
  2. **Race condition khi resume video chưa tải xong:** Khi trình duyệt tải trang, nếu hàm Anti-AFK kích hoạt và gọi `video.play()` trong khi phần tử video chưa sẵn sàng (`readyState < 2`), JavaScript ném ngoại lệ `DOMException` làm crash state machine của trình phát YouTube.
- **Ý nghĩa giải pháp:** Cho phép toàn bộ luồng truyền tải video chunk chạy thẳng ở tốc độ phần cứng (Pure Direct HTTP/3 QUIC) qua CDN `c.youtube.com`, bảo toàn 100% tính năng chặn quảng cáo thông qua lọc API Innertube mà không gây lỗi phát video.

---

## 3. Mối liên hệ
- **`backend/proxify/utils/youtube_utils.py`:** Chịu trách nhiệm phân tích request ad và xử lý mutation dữ liệu Innertube.
- **`backend/extensions/youtube/extension.py`:** Khai báo cấu trúc định tuyến cho hệ thống Extension Core.
- **`docker-compose.yml` & Windows `ProxyOverride`:** Bảo đảm luồng TCP Passthrough đồng bộ 2 lớp giữa hệ điều hành và proxy server.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Domain CDN mới phát sinh của Google:** Nếu YouTube trong tương lai mở rộng thêm các domain streaming mới khác ngoài `googlevideo.com` và `c.youtube.com`, cần giám sát qua log `requests` để tiếp tục bổ sung vào danh sách passthrough.
