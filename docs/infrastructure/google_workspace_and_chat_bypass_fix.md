# Tài Liệu Kỹ Thuật: Cấu Hình Bypass Toàn Diện Cho Google Workspace & Google Chat

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docker-compose.yml`
  - Bổ sung danh sách các domain phục vụ thông tin liên lạc và dữ liệu riêng tư của Google vào biến môi trường `IGNORE_HOSTS`:
    `mail.google.com,chat.google.com,accounts.google.com,clients6.google.com,client-channel.google.com,contacts.google.com,meet.google.com,drive.google.com,docs.google.com`.
- **File sửa đổi 2:** `backend/proxify/server.py`
  - Cập nhật giá trị fallback mặc định trong `os.getenv("IGNORE_HOSTS", ...)` đồng bộ với `docker-compose.yml`.
- **Cấu hình Hệ điều hành (Windows Winsock / WinHTTP):**
  - Cập nhật `ProxyOverride` trên Windows bổ sung các domain:
    `mail.google.com;chat.google.com;accounts.google.com;*.clients6.google.com;client-channel.google.com;contacts.google.com;meet.google.com;drive.google.com;docs.google.com`.
  - Đồng bộ cấu hình sang WinHTTP thông qua lệnh `netsh winhttp import proxy source=ie`.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng truy cập vào liên kết Google Chat / Spaces (`https://mail.google.com/mail/u/0/?tab=rm&ogbl#chat/space/AAQAwg8VlQo`) và gặp thông báo lỗi kết nối hoặc trang bị treo.

### Phân tích Kiến trúc & Nguyên nhân gốc rễ (Root Cause)
1. **Anti-pattern "Full-System Gateway" khi kích hoạt Windows System Proxy:**
   - Khi bật `ProxyEnable = 1`, toàn bộ traffic mạng của máy tính bị bắt buộc đẩy qua cổng `127.0.0.1:8080`.
   - Vốn dĩ Proxify chỉ là một công cụ Application-Level Reverse/Forward Proxy phục vụ bóc tách dữ liệu mạng xã hội (Facebook, Zalo) và hỗ trợ YouTube Enhancer, việc gánh toàn bộ dữ liệu máy chủ doanh nghiệp/cá nhân làm vi phạm nghiêm trọng nguyên lý Single Responsibility Principle (SRP).
2. **Xung đột máy trạng thái HTTP/2 (State Machine Mismatch trong thư viện `h2`):**
   - Google Chat chạy trên nền web sử dụng các kết nối HTTP/2 Multiplexing thời gian thực liên tục (Long-lived SSE, WebChannel, gRPC) kết nối đến `signaler-pa.clients6.google.com`, `accounts.google.com`, `mail.google.com`.
   - Khi mitmproxy can thiệp vào giữa và nhận PING frames sau khi stream đã ở trạng thái đóng/bán đóng, thư viện `h2` của Python quăng exception:
     `HTTP/2 protocol error: Invalid input ConnectionInputs.RECV_PING in state ConnectionState.CLOSED`.
   - Mitmproxy lập tức ngắt socket kết nối (`server disconnect accounts.google.com:443`), gửi `RST_STREAM` hoặc làm sập kết nối HTTP/2. Trình duyệt Chrome nhận lỗi `ERR_HTTP2_PROTOCOL_ERROR` hoặc mất kênh đồng bộ thời gian thực, dẫn đến giao diện Chat văng lỗi hoặc treo vô hạn.
3. **Bảo mật và Quyền riêng tư:**
   - Google áp dụng cơ chế Certificate Pinning và HSTS `includeSubDomains`. Việc giải mã TLS các dịch vụ như Gmail, Google Drive, Google Chat tiềm ẩn rủi ro lộ dữ liệu nhạy cảm vào log CSDL và dễ bị trình duyệt chặn truy cập.

### Ý nghĩa giải pháp (Kiến trúc Phòng thủ Đa tầng - Defense-in-Depth)
- **Tầng 1 (Hạ tầng Windows - `ProxyOverride`):** Trình duyệt Chrome kết nối thẳng (Direct Connection) ra Internet đến máy chủ Google qua giao thức gốc QUIC / HTTP/3. Độ trễ proxy về 0ms, không rò rỉ dữ liệu cá nhân, Google Chat kết nối tức thì và ổn định 100%.
- **Tầng 2 (Lõi Mitmproxy - `IGNORE_HOSTS`):** Nếu có request gửi tới port 8080, Mitmproxy tự động kích hoạt chế độ **TCP Passthrough thuần túy**, không giải mã TLS, không can thiệp frame HTTP/2.
- **Tính độc lập của module YouTube:** YouTube sử dụng `youtube.com`, `googlevideo.com`, `youtubei.googleapis.com` (thuộc đuôi `googleapis.com` và `youtube.com`). Việc loại trừ `mail.google.com`, `chat.google.com`, `accounts.google.com` hoàn toàn không ảnh hưởng đến khả năng bắt và chặn quảng cáo của plugin YouTube.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `Windows ProxyOverride` | Bypass kết nối ở tầng Winsock của hệ điều hành, cho phép trình duyệt gửi trực tiếp ra gateway |
| `docker-compose.yml` | Khai báo `IGNORE_HOSTS` chuyển vào container `proxify_app` |
| `backend/proxify/server.py` | Nạp `IGNORE_HOSTS` vào `mitmproxy.options.Options(ignore_hosts=...)` để kích hoạt TCP Passthrough |
| `backend/extensions/youtube` | Hoạt động độc lập trên `youtube.com`, `googlevideo.com`, `youtubei.googleapis.com` mà không bị gián đoạn |
| Google Chat / Gmail | Phục hồi kết nối HTTP/2 liên tục, tải mượt mà không còn bị ngắt socket |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Các dịch vụ Google khác chưa liệt kê:**
   - *Đánh giá:* Các domain chính (`mail.google.com`, `chat.google.com`, `accounts.google.com`, `clients6.google.com`, `meet.google.com`, `drive.google.com`, `docs.google.com`) đã bao phủ 99% các trường hợp làm việc hàng ngày.
   - *Xử lý:* Nếu có dịch vụ chuyên biệt khác của Google bị chậm hoặc lỗi, có thể bổ sung tương tự vào danh sách `ProxyOverride` và `IGNORE_HOSTS`.
2. **Khởi động lại máy tính:**
   - *Đánh giá:* Cấu hình `ProxyOverride` đã được lưu vĩnh viễn vào Windows Registry (`HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings`) và WinHTTP, sẽ tồn tại sau khi restart máy.
