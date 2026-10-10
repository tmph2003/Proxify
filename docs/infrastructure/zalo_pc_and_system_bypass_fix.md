# Tài Liệu Kỹ Thuật: Cấu Hình Bypass Toàn Diện Cho Zalo PC và Dịch Vụ Nền Hệ Thống

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docker-compose.yml`
  - Bổ sung toàn bộ các domain của hệ sinh thái Zalo vào biến môi trường `IGNORE_HOSTS`:
    `zalo.me,chat.zalo.me,zaloapp.com,zadn.vn,zing.vn`.
- **File sửa đổi 2:** `backend/proxify/server.py`
  - Cập nhật giá trị mặc định của biến `IGNORE_HOSTS` trong fallback `os.getenv` đồng bộ với `docker-compose.yml`.
- **Cấu hình Hệ điều hành (Windows Registry & WinHTTP):**
  - Cập nhật danh sách `ProxyOverride` trên Windows:
    `localhost;127.0.0.1;*.company.com.vn;14.232.214.249;*.zalo.me;*.zaloapp.com;*.zadn.vn;*.zing.vn;*.microsoft.com;*.live.com;*.office.com;*.windowsupdate.com;<local>`
  - Đồng bộ cấu hình sang tầng WinHTTP qua lệnh `netsh winhttp import proxy source=ie`.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng phản ánh: *"tự dưng nó còn làm chậm mạng của tôi hay sao ấy, cả văn phòng mỗi mình tôi ping cao, với zalo pc còn không cả nhận được tin nhắn, có gì ignore host của zalo pc đi nhé"*.

### Phân tích Kiến trúc & Nguyên nhân gốc rễ (Root Cause)
1. **Nghẽn cổ chai Event Loop do gom toàn bộ Network Traffic vào Proxy (Anti-pattern):**
   - Khi bật System Proxy (`ProxyEnable = 1`), tất cả các ứng dụng desktop trên Windows (bao gồm Zalo PC, OneDrive sync, Teams, Windows Update telemetry, Office background sync) đều bị dồn qua duy nhất 1 cổng `127.0.0.1:8080`.
   - Proxy mitmproxy trong container chạy trên Single Thread Python Event Loop. Khi gánh đồng thời hàng ngàn kết nối ngầm của hệ điều hành kèm streaming đa phương tiện, buffer mạng bị tràn, TCP handshake bị nghẽn dẫn tới việc ping mạng toàn máy tăng đột biến so với các máy khác trong cùng mạng LAN văn phòng.
2. **Nguyên nhân Zalo PC mất kết nối / không nhận tin nhắn:**
   - Zalo PC (Native Desktop App) duy trì các kênh kết nối thời gian thực dạng **Long-lived WebSockets & TCP Raw Sockets** (`ws*-msg.chat.zalo.me`, `tt-chat*-wpa.chat.zalo.me`) với cơ chế Heartbeat (Ping/Pong) nghiêm ngặt.
   - Khi đi qua mitmproxy, proxy cố gắng giải mã TLS và can thiệp WebSocket. Các cơ chế quản lý timeout như `Closing connection due to inactivity` hoặc độ trễ xử lý khiến socket bị ngắt liên tục (`server disconnect tt-chat3-wpa.chat.zalo.me`), làm đứt gãy luồng đồng bộ tin nhắn đẩy (push notification) của Zalo PC.
   - Theo nguyên lý **Separation of Concerns (SoC)**, Proxify là công cụ phục vụ bóc tách dữ liệu mạng xã hội trên nền tảng Web (`chat.zalo.me`, `facebook.com`), việc can thiệp vào Native Desktop App của Zalo không mang lại giá trị trích xuất mà phá vỡ tính ổn định của ứng dụng người dùng.

### Ý nghĩa giải pháp (Kiến trúc Phòng thủ Đa tầng - Defense-in-Depth)
- **Tầng 1 (Hệ điều hành - Winsock Layer):** Khai báo `ProxyOverride` trên Windows. Zalo PC và các dịch vụ nền Windows (OneDrive, Office, Update) sẽ kết nối **trực tiếp 100% ra Internet** qua Gateway công ty mà không hề chạm tới port 8080 của Proxy. Độ trễ về mức 0ms overhead, socket WebSocket được bảo toàn nguyên vẹn.
- **Tầng 2 (Mitmproxy Passthrough Layer):** Cấu hình `IGNORE_HOSTS` đảm bảo nếu bất kỳ ứng dụng nào bỏ qua cấu hình Windows mà gửi thẳng CONNECT request đến proxy, mitmproxy sẽ lập tức kích hoạt chế độ **TCP Passthrough thô**, không giải mã TLS, không can thiệp gói tin, truyền dẫn trực tiếp ở tốc độ cáp mạng.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `Windows ProxyOverride` | Bypass kết nối ở tầng Winsock của hệ điều hành, giải phóng tải cho Proxy |
| `docker-compose.yml` | Truyền danh sách `IGNORE_HOSTS` dạng biến môi trường vào container `proxify_app` |
| `backend/proxify/server.py` | Nạp `IGNORE_HOSTS` và truyền vào `mitmproxy.options.Options(ignore_hosts=...)` |
| `backend/proxify/core/router.py` | Kiểm tra `is_ignored(host)` để bỏ qua xử lý routing nội bộ |
| Zalo PC (`Zalo.exe`) | Được giải phóng kết nối, nhận tin nhắn và gọi thoại thời gian thực trơn tru |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Zalo Web (`chat.zalo.me`) trên trình duyệt Chrome:**
   - *Đánh giá:* Khi thêm `*.zalo.me` vào `ProxyOverride`, trình duyệt Chrome cũng sẽ bypass proxy khi truy cập `chat.zalo.me`. Nếu người dùng muốn sử dụng Zalo Extractor của Proxify, họ cần truy cập qua profile Chrome có flag `--proxy-server` hoặc cấu hình extension riêng.
   - *Trade-off (Đánh đổi):* Đây là đánh đổi tối ưu và cần thiết để đảm bảo ứng dụng làm việc hàng ngày của người dùng (Zalo PC) hoạt động 100% ổn định và giải quyết triệt để tình trạng nghẽn mạng văn phòng.
