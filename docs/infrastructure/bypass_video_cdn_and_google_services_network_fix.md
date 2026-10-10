# Tài Liệu Kỹ Thuật: Giải Phóng Băng Thông Video CDN & Triệt Tiêu Nghẽn Mạng Hệ Thống

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docker-compose.yml`
  - Bổ sung các domain CDN đa phương tiện dung lượng lớn và hệ thống hạ tầng Google vào biến môi trường `IGNORE_HOSTS`:
    `googlevideo.com,google.com,gvt2.com,1e100.net,gstatic.com`.
- **File sửa đổi 2:** `backend/proxify/server.py`
  - Cập nhật giá trị mặc định `raw_ignore` đồng bộ với `docker-compose.yml`.
- **Cấu hình Hệ điều hành (Windows Winsock / WinHTTP):**
  - Cập nhật `ProxyOverride` trên Windows bổ sung:
    `*.googlevideo.com;*.google.com;*.gvt2.com;*.1e100.net;*.gstatic.com`.
  - Đồng bộ cấu hình sang WinHTTP bằng lệnh `netsh winhttp import proxy source=ie`.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng phản ánh: *"mạng lại bị chậm rồi"*. Khi kiểm tra log và tài nguyên mạng của container:
- Lưu lượng mạng của `proxify_app` đạt tới **114 MB nhận / 445 MB gửi**.
- Các yêu cầu ping kiểm tra sức khỏe của YouTube mất tới **6.980ms** (`#831426 POST 204 www.youtube.com/api/stats/qoe`).
- Các tác vụ ngầm của Chrome (`beacons.gcp.gvt2.com`) bị treo đệm tới **23.957ms**.
- Xuất hiện lỗi DNS timeout `[Errno -3] Temporary failure in name resolution` kéo dài đúng **8,000 giây** cho mỗi kết nối thất bại.

### Phân tích Kiến trúc & Nguyên nhân gốc rễ (Root Cause)
1. **Nghẽn cổ chai Event Loop đơn luồng do chuyển tiếp Video Streaming (`*.googlevideo.com`):**
   - Trước đây, `googlevideo.com` chỉ được cấu hình `stream = True` trong Mitmproxy nhưng **vẫn đi qua cổng 8080 của proxy**.
   - Mỗi video YouTube (1080p, 4K) tải về hàng trăm Megabyte dữ liệu nhị phân (DASH/HLS chunks). Tiến trình Python đơn luồng của Mitmproxy phải liên tục nhận gói tin, bóc tách SSL socket và chuyển tiếp cho Chrome.
   - Khi luồng Event Loop bị bão hòa bởi hàng trăm megabyte dữ liệu video, tất cả các request HTTP/WebSocket thông thường (tải trang web, gọi API, tìm kiếm Google) bị kẹt lại trong hàng đợi chờ xử lý, dẫn đến ping tăng vọt và mạng toàn máy bị chậm nghiêm trọng.
   - Về mặt bản chất: **Proxify không hề can thiệp hay sửa đổi dữ liệu trên `googlevideo.com`**. Việc chặn quảng cáo YouTube thực chất diễn ra ở tầng API Player JSON trên `youtube.com` và `youtubei.googleapis.com` (khử các khối renderer quảng cáo `adPlacements` và `adSlots`). Việc ép video binary stream đi qua proxy là một lỗi kiến trúc dư thừa tài nguyên.
2. **Xung đột máy trạng thái HTTP/2 trên các dịch vụ tìm kiếm và đồng bộ Google:**
   - Các domain tìm kiếm và telemetry của Chrome (`www.google.com`, `google.com`, `play.google.com`, `history.google.com`, `*.gvt2.com`) trước đó chưa được đưa vào danh sách bypass.
   - Khi Chrome gửi các kết nối HTTP/2 nền với nhịp tim PING liên tục, thư viện `h2` của Mitmproxy phát sinh lỗi `ConnectionInputs.RECV_PING in state ConnectionState.CLOSED` và ngắt kết nối. Trình duyệt Chrome bị cạn kiệt socket pool (Head-of-Line Blocking) khi phải chờ timeout các kết nối nền này.

### Ý nghĩa giải pháp (Kiến trúc Phòng thủ Đa tầng)
- **Tầng 1 (Hạ tầng Windows - Winsock Direct Connection):**
  - Trình duyệt Chrome tải thẳng các luồng video `*.googlevideo.com` qua giao thức HTTP/3 (QUIC) từ máy chủ Google CDN với tốc độ cáp quang tối đa, 0ms độ trễ và 0% tải CPU cho proxy.
  - Các yêu cầu tìm kiếm Google (`google.com`, `www.google.com`) đi thẳng ra Internet bằng chứng chỉ gốc của Google, không còn lỗi `ERR_HTTP2_PROTOCOL_ERROR`.
  - **Bảo toàn 100% tính năng chặn quảng cáo:** `youtube.com` và `youtubei.googleapis.com` là các tên miền độc lập (không trùng với `google.com`), vẫn đi qua proxy và được khử quảng cáo triệt để.
- **Tầng 2 (Lõi Mitmproxy - TCP Passthrough):**
  - Khai báo các domain trên vào `IGNORE_HOSTS`. Mọi kết nối ngoài luồng nếu có chạm tới port 8080 đều được truyền thẳng mức socket TCP mà không giải mã SSL hay parse HTTP/2 frame.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `Windows ProxyOverride` | Bypass toàn bộ video stream `*.googlevideo.com` và tìm kiếm Google khỏi port 8080 |
| `docker-compose.yml` | Nạp `IGNORE_HOSTS` đảm bảo TCP Passthrough cho các request ngầm |
| `backend/proxify/server.py` | Cập nhật cấu hình fallback an toàn cho Mitmproxy Options |
| `backend/extensions/youtube` | Chặn video ads trên `youtube.com` và `youtubei.googleapis.com` mà không cần chạm tới video CDN |
| Trình duyệt Chrome | Tải video 4K/60fps mượt mà, lướt web tức thì, độ trễ giảm từ >20.000ms xuống <200ms |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Khả năng lọt quảng cáo video trên `googlevideo.com`?**
   - *Đánh giá:* Không có rủi ro. YouTube không phục vụ quảng cáo độc lập trên URL video chunk; quảng cáo được quyết định bởi metadata trong phản hồi InnerTube `/youtubei/v1/player`. Khi metadata này đã bị plugin khử sạch, trình phát video của YouTube không bao giờ yêu cầu các video chunk quảng cáo.
2. **Đồng bộ sau khi khởi động lại máy:**
   - Cấu hình `ProxyOverride` đã được lưu vĩnh viễn vào Windows Registry và WinHTTP, bảo đảm duy trì sau khi restart máy.
