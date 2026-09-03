# Tài Liệu Kỹ Thuật: Module `backend/proxify/platforms/facebook/auth.py`

## 1. Tóm tắt thay đổi
- **Hợp nhất mã nguồn**:
  - Tích hợp toàn bộ logic từ `token_store.py` và `auth_fetcher.py` thành một module duy nhất `auth.py`.
- **Cơ chế xác thực & quản lý phiên**:
  - `IN_MEMORY_TEMPLATES`: Bộ nhớ đệm RAM lưu trữ các template GraphQL và credential trích xuất từ trình duyệt (Zero-Disk Persistence).
  - `save_session_cache()` / `load_session_cache()`: No-op functions nhằm tuân thủ nguyên tắc không lưu cookie xuống file đĩa hoặc database.
  - `parse_cookie_string(cookie_str)`: Chuẩn hóa chuỗi cookie từ client extension hoặc header.
  - `extract_tokens_from_template(template)`: Trích xuất các tham số cốt lõi `fb_dtsg`, `lsd`, `jazoest`, `c_user`.
  - `fetch_fb_auth_tokens(cookie_str, ...)`: Gửi request ngầm kiểm tra tính hợp lệ của cookie và bóc tách token trực tiếp từ mã nguồn HTML Facebook.

---

## 2. Mục đích & Ý nghĩa
- **Bảo mật tuyệt đối (Zero-Disk Persistence)**: Cookie và session token chỉ được lưu tạm trên RAM và truyền qua Chrome Extension `localStorage`, ngăn ngừa rò rỉ thông tin đăng nhập ra file cứng.
- **Tập trung hóa nghiệp vụ Auth**: Gom toàn bộ việc phân tích cookie, bóc tách token và xác thực checkpoint tài khoản về một đầu mối duy nhất.

---

## 3. Mối liên hệ
- Được gọi bởi `api.py` (`FacebookAPI`) để kiểm tra trạng thái cookie, cập nhật template từ extension.
- Cung cấp token và header sạch cho `crawler.py` (`FacebookCrawler`) trước khi thực hiện cào bảng tin hoặc bình luận.

---

## 4. Rủi ro & Edge Cases
- **Cookie hết hạn hoặc bị Facebook Checkpoint**: `fetch_fb_auth_tokens` chủ động phát hiện trang chuyển hướng checkpoint và trả về `success=False` kèm cảnh báo chi tiết thay vì để crawler gửi request lỗi hàng loạt.
