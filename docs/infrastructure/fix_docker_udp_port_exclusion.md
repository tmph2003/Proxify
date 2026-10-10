# Tài Liệu Kỹ Thuật: Khắc Phục Xung Đột Port UDP 51920 & Lỗi Port Proxy Bị Từ Chối Trên Windows

## 1. Tóm tắt thay đổi
- Trong file `docker-compose.yml`, tạm thời comment out (vô hiệu hóa) dòng ánh xạ cổng UDP:
  ```yaml
  # - "51920:51820/udp" # Tạm tắt do trùng dải dynamic port exclusion của Windows Hyper-V
  ```

## 2. Mục đích & Ý nghĩa
- **Vấn đề thực tế:** Khi khởi động container `proxify_app`, Docker daemon trên Windows báo lỗi:
  ```text
  Error response from daemon: ports are not available: exposing port UDP 0.0.0.0:51920 -> 127.0.0.1:0: listen udp 0.0.0.0:51920: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
  ```
- **Nguyên nhân gốc rễ:** Windows Hyper-V / Host Network Service (HNS) tự động dành riêng các dải cổng động ngẫu nhiên (Excluded Port Ranges). Lệnh kiểm tra `netsh int ipv4 show excludedportrange protocol=udp` cho thấy cổng `51920` nằm trọn trong dải bị Windows cấm: `51914 - 52013`.
- **Hệ quả dây chuyền:** Do không bind được cổng UDP này, Docker không thể khởi tạo cấu hình Network / Ports cho container `proxify_app`, khiến cổng proxy chính `8080` cũng không được publish ra host (`NetworkSettings.Ports: []`). Khi người dùng cấu hình proxy trỏ về `127.0.0.1:8080`, toàn bộ kết nối bị `Connection Refused` dẫn đến hiện tượng **mất mạng hoàn toàn**.
- **Giải pháp:** Cổng `51820` (WireGuard legacy) hiện không có bất kỳ service nào trong Proxify sử dụng. Việc tắt dòng này giải phóng container, giúp Docker publish thành công cổng `8080` (Mitmproxy) ra máy host.

## 3. Mối liên hệ
- Liên quan trực tiếp tới:
  - `docker-compose.yml`: Định nghĩa các port bind ra ngoài host Windows.
  - `proxify/server.py`: Mitmproxy lắng nghe trên port 8080 TCP.
  - Cấu hình mạng trên Windows (`127.0.0.1:8080`) hoặc extension (SwitchyOmega / Proxify Helper).

## 4. Rủi ro (Risks & Edge Cases)
- **WireGuard VPN trong tương lai:** Nếu dự án tích hợp thêm VPN WireGuard client/server chạy cổng UDP 51820, cần chọn một cổng bên ngoài host khác (ví dụ: `51821` hoặc `45000`) không nằm trong danh sách `excludedportrange` của Windows.
- **Port 8080:** Nếu người dùng cài phần mềm khác chiếm port 8080 (như Apache, Tomcat, IIS alternate), container vẫn có thể bị xung đột cổng TCP. Khi đó cần chuyển `PROXY_PORT` sang `8081` hoặc `8899`.
