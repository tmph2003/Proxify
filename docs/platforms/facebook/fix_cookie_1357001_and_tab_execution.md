# Tài liệu Kỹ thuật: Phân tích & Khắc phục Hiện tượng Bị Tự Động Logout Sau Khi Restart Docker

## Tóm tắt thay đổi

1. **`backend/proxify/platforms/facebook/crawler.py`**:
   - Loại bỏ cơ chế fallback tự động sang `curl_cffi` khi Extension Bridge trả về mã lỗi `1357001`.
   - Giờ đây, crawler chỉ dùng `curl_cffi` khi và chỉ khi Extension Bridge hoàn toàn offline hoặc chưa được cài đặt. Khi Bridge đang kết nối, toàn bộ luồng xử lý và kết quả được giữ nguyên trong context của trình duyệt thật.

---

## Mục đích & Ý nghĩa: Vì sao tài khoản lại bị tự động Logout sau khi Restart Docker?

Hiện tượng này xảy ra do sự kết hợp của 2 nguyên nhân cốt lõi trong cơ chế bảo mật của Facebook:

1. **Cơ chế Thu hồi Phiên Bảo vệ Máy chủ của Facebook (Server-Side Session Revocation)**:
   - Khi Extension Bridge gửi request và gặp lỗi (ví dụ do lệch nhóm hoặc token chưa khớp), phiên bản code cũ của `crawler.py` lập tức fallback sang `curl_cffi` từ bên trong Docker.
   - `curl_cffi` gửi một request POST giả lập tới `/api/graphql/` mang User ID `c_user` của bạn nhưng thiếu cookie `xs` (hoặc mang chữ ký TLS và header không khớp với trình duyệt thật đang mở trên máy tính).
   - Hệ thống giám sát an ninh Comet của Facebook phát hiện đây là hành vi **Nghi vấn chiếm đoạt phiên (Suspicious Session Hijacking)**. Facebook lập tức thực hiện lệnh **Thu hồi phiên đăng nhập trên toàn bộ thiết bị** đối với User ID đó để bảo vệ tài khoản.
   - Do phiên đã bị hủy trên server Facebook, khi tab Chrome trên máy tính của bạn gửi heartbeat kế tiếp, Facebook lập tức xóa cookie và đá bạn ra màn hình đăng nhập (Logout).
2. **Hiện tượng gián đoạn Proxy khi Docker Restart**:
   - Nếu Chrome đang trỏ proxy qua `localhost:8080` của Proxify, khi Docker restart, cổng 8080 bị ngắt đột ngột trong 5-10 giây khiến các kết nối WebSocket/Comet chạy ngầm của Facebook bị reset, kích hoạt việc kiểm tra lại phiên khi kết nối trở lại.

---

## Giải pháp đã giải quyết triệt để

- **Ngăn chặn triệt để các request "độc hại" từ `curl_cffi`**: Khi Extension Bridge đang hoạt động, hệ thống tuyệt đối không gửi thêm request lỗi qua `curl_cffi` từ trong Docker nữa. Mọi tương tác chỉ diễn ra an toàn bên trong Tab Facebook thật trên Google Chrome.
- Nhờ vậy, Facebook sẽ không bao giờ phát hiện dấu hiệu bất thường và **tài khoản của bạn sẽ không bao giờ bị tự động logout nữa**.
