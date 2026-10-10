# Khắc phục lỗi Crash Loop Database và DNS Cache 502 Bad Gateway trên Nginx

## 1. Tóm tắt thay đổi
- **Cập nhật `docker-compose.yml`**: Bổ sung `restart: unless-stopped` cho service `db` (PostgreSQL 15).
- **Cập nhật `frontend/nginx.conf`**:
  - Bổ sung cấu hình Docker Internal DNS Resolver: `resolver 127.0.0.11 valid=10s ipv6=off;`.
  - Sử dụng biến động `$backend_upstream http://proxify:8888;` và chuyển tiếp `$backend_upstream$request_uri` trong directive `proxy_pass`.
- **Cập nhật hot runtime**: Copy cấu hình mới vào container `proxify_ui` và gửi tín hiệu reload Nginx mà không cần downtime.

## 2. Mục đích & Ý nghĩa
### Vấn đề gốc (Root Causes)
1. **Database Container Crash (Exit Code 255) & Backend Crash Loop:**
   - Container `proxify_db` bị dừng khi máy tính sleep/khởi động lại hoặc docker daemon restart do thiếu thuộc tính `restart: unless-stopped` (trong khi `proxify_app` và `proxify_ui` đều có).
   - Khi `proxify_app` khởi động, nó tìm hostname `db:5432` nhưng container `db` chưa chạy, dẫn đến lỗi mạng `socket.gaierror: [Errno -5] No address associated with hostname` và khiến backend rơi vào vòng lặp crash liên tục.
2. **Nginx DNS Cache Lock (502 Bad Gateway):**
   - Khi `proxify_db` và `proxify_app` được khởi động lại, Docker gán lại địa chỉ IP nội bộ (`172.19.0.x`) cho các container.
   - Nginx theo mặc định chỉ phân giải tên miền upstream (`http://proxify:8888`) một lần duy nhất lúc khởi động container `proxify_ui` và ghi nhớ IP đó vĩnh viễn. Khi IP container thay đổi (IP cũ của backend bị chuyển sang DB), Nginx gửi request đến sai IP và bị từ chối kết nối (`connect() failed (111: Connection refused)`), sinh mã lỗi HTTP 502 Bad Gateway cho toàn bộ UI và Extension Bridge.

### Giải pháp
- Đảm bảo cơ sở dữ liệu luôn tự động chạy lại đồng bộ cùng hệ thống.
- Bắt buộc Nginx phải truy vấn DNS máy chủ ảo hóa nội bộ của Docker (`127.0.0.11`) với TTL tối đa 10 giây, loại bỏ hoàn toàn rủi ro 502 Bad Gateway mỗi khi restart backend.

## 3. Mối liên hệ
- **Hạ tầng Docker:** `docker-compose.yml` định nghĩa vòng đời của các container `proxify_db`, `proxify_app`, `proxify_ui`.
- **Giao diện & Extension:** `proxify_ui` (Nginx) phục vụ React Dashboard và là cổng đảo ngược (reverse proxy) cho Chrome Extension giao tiếp với API backend (`/api/facebook/bridge/jobs`).

## 4. Rủi ro (Risks & Edge Cases)
- **IPv6 Resolution:** Nếu không có cờ `ipv6=off`, Nginx có thể cố gắng phân giải bản ghi AAAA trên Docker network gây chậm trễ (delay) vài giây cho mỗi request lần đầu. Do đó, cờ `ipv6=off` đã được chủ động bật để đảm bảo tốc độ phản hồi tính bằng mili-giây.
- **WebSocket Timeout:** Cần đảm bảo kết nối WebSocket `/ws` được duy trì đúng header nâng cấp giao thức `Upgrade` và `Connection` (đã được kiểm tra và cấu hình sẵn).
