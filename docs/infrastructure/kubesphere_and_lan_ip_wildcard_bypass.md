# Tài liệu Kỹ thuật: Cơ chế Bypass Wildcard IP Mạng Nội Bộ (LAN) & Khắc Phục Nghẽn Socket KubeSphere (`ks.sunhouse.com.vn`)

## 1. Tóm tắt thay đổi
- **Hạ tầng Proxy Core (`backend/proxify/server.py`):**
  - Cải tiến logic biên dịch danh sách `IGNORE_HOSTS` thành `ignore_patterns` của Mitmproxy: Bổ sung khả năng nhận diện ký tự đại diện wildcard IP (`*`). Khi gặp mẫu như `172.16.*`, hệ thống sẽ tự động sinh regex tiền tố `^172\.16\..*` để ép buộc Mitmproxy kích hoạt `TCPLayer` (Pure TCP Passthrough) cho toàn bộ dải IP con `172.16.x.x:port`, thay vì chỉ áp dụng regex hậu tố domain `(?::|$)`.
  - Nâng cấp bộ lọc `ProxyRouter.handle_response`: Bổ sung điều kiện kiểm tra tiền tố `(h.endswith('*') and domain.startswith(h.rstrip('*')))` nhằm loại bỏ triệt để việc xử lý, ghi log hoặc đẩy dữ liệu vào CSDL/WebSocket đối với traffic mạng nội bộ IP.
  - Cập nhật giá trị mặc định của `IGNORE_HOSTS` bao gồm `172.16.*`.
- **Cấu hình Triển khai (`docker-compose.yml`):**
  - Bổ sung `172.16.*` vào biến môi trường `IGNORE_HOSTS` của service `proxify`.
- **Cấu hình Hệ thống & Trình duyệt (Windows Registry & WinINet):**
  - Cập nhật `ProxyOverride` chứa đầy đủ: `*.sunhouse.com.vn;.sunhouse.com.vn;sunhouse.com.vn;172.16.*;172.16.0.0/12`.
  - Thực thi Win32 API `InternetSetOption` (`INTERNET_OPTION_SETTINGS_CHANGED` và `INTERNET_OPTION_REFRESH`) nhằm thông báo cho toàn bộ các tiến trình đang chạy (đặc biệt là Network Service của Chromium) nạp lại bảng định tuyến proxy mới mà không yêu cầu khởi động lại máy.

---

## 2. Mục đích & Ý nghĩa
- **Hiện tượng:** Khi người dùng truy cập KubeSphere tại `https://ks.sunhouse.com.vn` (phân giải ra IP nội bộ `172.16.100.130` qua VPN GlobalProtect), trang tải rất chậm hoặc bị đơ ở màn hình loading animation.
- **Nguyên nhân cốt lõi:**
  1. **Socket Pool Reuse của Chromium:** Tiến trình `chrome.exe` (PID 9320) đã chạy liên tục từ trước khi cập nhật Registry. Do Windows Registry chỉ là lưu trữ tĩnh, nếu không gọi Win32 API `InternetSetOption`, Chromium không nhận được thông điệp thay đổi proxy và tiếp tục tái sử dụng các TCP keep-alive socket đang mở tới `127.0.0.1:8080`.
  2. **NAT Routing Loop 4 Chặng khi đi qua Proxy:** Khi traffic tới `ks.sunhouse.com.vn` đi vào `127.0.0.1:8080`, gói tin bị đẩy qua Docker Bridge (`172.19.0.2`) -> Hyper-V Virtual Switch (`172.19.0.1`) -> Windows Host Routing -> Palo Alto GlobalProtect Adapter (`172.16.107.233`) -> Gateway VPN -> Ingress K8s (`172.16.100.130`). Điều này gây độ trễ handshake và nghẽn tài nguyên event loop so với kết nối trực tiếp.
  3. **Lỗ hổng Regex IP Wildcard:** Regex cũ `rf"(?:^|\.){re.escape(h)}(?::|$)"` chỉ hoạt động cho domain FQDN. Với dải IP như `172.16.*`, `re.escape` biến thành `172\.16\.\*`, khiến Mitmproxy không nhận diện được IP `172.16.100.130` là ignored host nếu client kết nối bằng raw IP.
- **Ý nghĩa giải pháp:** Đảm bảo toàn bộ lưu lượng Sunhouse (cả domain FQDN, subdomain KubeSphere/ERP/GitLab/Trino lẫn IP trực tiếp `172.16.*`) được giải phóng hoàn toàn khỏi Proxy ở tầng hệ điều hành, đồng thời có lớp bảo vệ thứ hai tại Proxy Core để không can thiệp vào traffic nội bộ.

---

## 3. Mối liên hệ
- **`backend/proxify/server.py`:** Chịu trách nhiệm khởi tạo `DumpMaster` và cấu hình `ignore_hosts`. Ảnh hưởng trực tiếp đến việc Mitmproxy có giải mã TLS hay chỉ bọc `TCPLayer`.
- **`docker-compose.yml`:** Định nghĩa biến môi trường cho container `proxify_app`.
- **Hệ thống mạng Host & GlobalProtect VPN:** Liên kết giữa card mạng Wi-Fi ngoài (`192.168.100.1`) và card ảo VPN Palo Alto (`172.16.100.5` / `172.16.107.233`).
- **Trình duyệt Client (Chrome/Edge):** Tác động tới cơ chế phân giải `ProxyResolutionService` và bộ đệm kết nối `ClientSocketPoolManager`.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Chromium In-Flight Sockets:** Mặc dù đã gọi Win32 API `InternetSetOption`, đối với các tab đang mở sẵn và giữ kết nối HTTP/2 hoặc WebSocket mở liên tục tới proxy, Chromium có thể giữ socket đó cho tới khi kết nối bị đóng hoặc timeout. Cách xử lý triệt để nhất từ phía người dùng là mở một tab mới hoàn toàn hoặc đóng các tab Sunhouse cũ để Chromium khởi tạo socket mới trực tiếp.
- **Dải IP Private khác:** Hiện tại đã mở dải `172.16.*` (và CIDR `172.16.0.0/12`). Nếu Sunhouse triển khai thêm dải mạng nội bộ thuộc `10.0.0.0/8` hoặc `192.168.0.0/16`, cần bổ sung tương ứng vào danh sách bypass.
