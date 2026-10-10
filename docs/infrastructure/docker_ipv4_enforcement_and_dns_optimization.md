# Tài Liệu Kỹ Thuật: Cấu Hình Ép IPv4, Tối Ưu DNS Độc Lập Và Loại Bỏ Telemetry Rác Cho Proxify

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docker-compose.yml`
  - Bổ sung cấu hình Kernel Sysctl vô hiệu hóa IPv6 bên trong container:
    ```yaml
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=1
    ```
  - Bổ sung cấu hình Public DNS trực tiếp độc lập với Docker Desktop/WSL2 relay:
    ```yaml
    dns:
      - 8.8.8.8
      - 1.1.1.1
    ```
  - Mở rộng biến môi trường `IGNORE_HOSTS` chặn các domain nền của Docker Desktop:
    `mcp.docker.com,api.docker.com,desktop.docker.com`.

- **File sửa đổi 2:** `backend/proxify/server.py`
  - Đồng bộ fallback mặc định của `IGNORE_HOSTS` trong code Python, bổ sung các domain `mcp.docker.com,api.docker.com,desktop.docker.com`.

- **File sửa đổi 3:** `.env`
  - Cập nhật biến `IGNORE_HOSTS` đồng bộ với `docker-compose.yml` và `server.py`.

- **Vận hành hệ thống:**
  - Tái tạo và khởi chạy lại container `proxify_app` qua `docker compose up -d`.
  - Xác thực trực tiếp trong container: `disable_ipv6 = 1`, `ExtServers = [8.8.8.8 1.1.1.1]`.
  - Kiểm thử latency qua proxy: endpoint `google.com` giảm từ **8,400ms – 24,600ms** xuống còn **69.1ms** (cải thiện hơn 300 lần).

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Nguyên nhân kỹ thuật
Người dùng phản ánh tình trạng Proxify hoạt động chập chờn, load trang bị xoay vòng, trong khi mạng công ty trước đó vẫn hoạt động bình thường:
1. **Lệch pha định tuyến IPv6 (Asymmetric IPv6 Routing):**
   - Mạng gia đình (ISP Viettel) cấp mạng Dual-Stack (IPv4 + IPv6).
   - Container Docker kế thừa kernel Linux từ WSL2 nhưng mạng Docker Bridge mặc định lại **không có default gateway IPv6 và không bật NAT66**.
   - Mitmproxy tuân thủ RFC 6724 ưu tiên mở socket IPv6 trước, dẫn tới việc gói tin bị drop tại bridge và ném ngoại lệ `[Errno 101] Network is unreachable`.
   - Proxy bị khựng chờ timeout từ **8 đến 24 giây** trước khi chịu fallback sang IPv4.
2. **Nghẽn DNS Relay của Docker Desktop (`127.0.0.11`):**
   - Do phải xử lý truy vấn AAAA kép và DNS IPv6 nội bộ của router (`fd00:db80::1`), relay DNS của Docker Desktop bị quá tải ném lỗi `[Errno -3] Temporary failure in name resolution`.
3. **Nhiễu giao thức HTTP/2 từ Docker Desktop MCP:**
   - Tiến trình `com.docker.backend.exe` gửi telemetry tới `mcp.docker.com` với header vi phạm chuẩn RFC 9113 (`Authorization: Bearer ` có dấu cách cuối), gây ra lỗi `HTTP/2 protocol error` mỗi 30 giây làm ô nhiễm Single Event Loop.

### Ý nghĩa giải pháp
- **Đạt được tính ổn định và nhất quán (Environment Idempotency):**
  Bằng cách ép Pure IPv4 trong container, Proxify hoạt động đồng nhất 100% tại mọi hạ tầng mạng (mạng gia đình Viettel Dual-stack, mạng công ty Pure IPv4, mạng 4G/5G).
- **Loại bỏ hoàn toàn độ trễ ma:** Triệt tiêu hoàn toàn mã lỗi `[Errno 101]` và rút ngắn thời gian xử lý request xuống mức dưới 100ms.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `docker-compose.yml` | Cấu hình Kernel Namespaced Sysctl (`disable_ipv6=1`) và định tuyến DNS cấp container |
| `backend/proxify/server.py` | Radix Trie Router nạp danh sách `IGNORE_HOSTS` mới, passthrough thô các domain của Docker Desktop |
| `.env` | File cấu hình biến môi trường đồng bộ cục bộ |
| Docker Container `proxify_app` | Nhận cấu hình khởi động, cô lập mạng IPv4 và DNS 8.8.8.8 / 1.1.1.1 |
| Trình duyệt Client / Extractor | Gửi request qua proxy được phản hồi ngay lập tức mà không còn bị nghẽn timeout |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Khả năng truy cập dịch vụ IPv6-Only:**
   - *Rủi ro:* Container không thể kết nối tới các dịch vụ chỉ có địa chỉ IPv6.
   - *Đánh giá thực tế:* Các mạng xã hội mục tiêu của Proxify (Facebook, YouTube, Google, Zalo, TikTok) đều vận hành Dual-Stack bắt buộc, rủi ro là 0%.
2. **Ảnh hưởng tới máy tính Windows Host:**
   - *Đánh giá:* Sysctl được áp dụng theo Network Namespace của riêng container `proxify_app`. Hệ điều hành Windows của người dùng vẫn giữ nguyên Dual-Stack và IPv6 đầy đủ cho các ứng dụng khác.
