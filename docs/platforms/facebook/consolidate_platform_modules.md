# Tài Liệu Kiến Trúc: Quy Hoạch & Hợp Nhất Module Facebook Theo Use-Case

## 1. Tóm tắt thay đổi
Hệ thống con Facebook (`backend/proxify/platforms/facebook/`) trước đây có 18 file nhỏ rải rác. Toàn bộ mã nguồn đã được tái cấu trúc và quy hoạch lại thành các module nghiệp vụ chuyên biệt, đồng thời **đã chuyển toàn bộ các lệnh import trong toàn dự án sang các module mới và xóa bỏ hoàn toàn 9 file thừa**, rút gọn thư mục từ 21 file xuống chỉ còn **12 file chuẩn mực**:

1. **`stealth.py` (Hợp nhất Delay, Session State, Rate Limiter)**:
   - Gom `delay.py` (chiến lược độ trễ Gaussian), `session_state.py` (đột biến form data `__req`, `__s`, `__spin_t`) và `network.py` (Borg pattern rate limiter ≥ 2.5s).
2. **`workflow.py` (Hợp nhất Commands, Observer, Task Queue)**:
   - Gom `commands.py` (Command Pattern), `observer.py` (Observer Pattern theo dõi tiến độ) và `queue_manager.py` (Hàng đợi SQLite bất đồng bộ và DLQ).
3. **`auth.py` (Hợp nhất Token Store, Cookie Parser, Auth Fetcher)**:
   - Gom `token_store.py` (quản lý `IN_MEMORY_TEMPLATES` thuần RAM) và `auth_fetcher.py` (kiểm tra Checkpoint, trích xuất `fb_dtsg`/`lsd` qua HTML).
4. **`database.py` (Hợp nhất PostgreSQL Database Facade & Repositories)**:
   - Gom `repository.py` (Author, Post, Comment, Config DAOs) trực tiếp vào `database.py`.
5. **Dọn dẹp triệt để (Zero-Dead-Files)**:
   - Toàn bộ 9 file cũ (`delay.py`, `session_state.py`, `network.py`, `commands.py`, `observer.py`, `queue_manager.py`, `auth_fetcher.py`, `token_store.py`, `repository.py`) đã được xóa bỏ hoàn toàn sau khi cập nhật toàn bộ import trong `crawler.py`, `api.py`, `plugins/facebook.py`, `core/worker.py`.

---

## 2. Mục đích & Ý nghĩa
- **Cắt giảm phân mảnh:** Từ 21 file hỗn độn, thư mục `facebook/` giờ chỉ còn 12 file rõ ràng, mỗi file đảm nhiệm một miền nghiệp vụ riêng biệt.
- **Tăng tính gắn kết (High Cohesion):** Những logic có chung use-case hoặc phụ thuộc mật thiết với nhau được đặt trong cùng một file, không còn tình trạng file chỉ có 30–50 dòng làm rối cây thư mục.
- **Không còn file thừa / file rác:** Không để lại file wrapper hay re-export trung gian.

---

## 3. Mối liên hệ
- `crawler.py` sử dụng `stealth.py` để tạo nhịp điệu và đột biến tham số, sử dụng `workflow.py` để gửi lệnh và cập nhật tiến độ cho `state_observer`.
- `api.py` đọc tiến độ từ `workflow.state_observer` và nạp template vào `auth.IN_MEMORY_TEMPLATES`.
- `database.py` quản lý toàn bộ tầng lưu trữ PostgreSQL cho tác giả, bài viết và bình luận.

---

## 4. Rủi ro & Kiểm thử
- **Đã kiểm thử import toàn diện:** Chạy script xác thực import cả 12 module không có bất kỳ lỗi nào.
- **Không còn bất kỳ import nào trỏ vào file cũ:** Quét toàn bộ codebase `backend/` bằng ripgrep xác nhận 100% sạch sẽ.

