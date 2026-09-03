# Tài liệu Kỹ thuật: Cơ Chế Ngắt Cào An Toàn & Toast Cảnh Báo Khi Mất Kết Nối Extension Bridge

## 1. Tóm tắt thay đổi

1. **`backend/proxify/platforms/facebook/crawler.py`**:
   - **Xóa bỏ hoàn toàn nhánh Fallback sang `curl_cffi` trong `_safe_request()`**: Khi Chrome Extension mất kết nối (Bridge offline hoặc tab Facebook bị đóng), crawler không còn gửi request GraphQL qua `curl_cffi` từ bên trong container Docker nữa.
   - **Thêm cơ chế Fail-Safe Disconnect**: Tự động kích hoạt cờ dừng cào `self._stop_flag = True`, đánh dấu trạng thái `status = 'error'`, và gửi thông báo Toast: *"⚠️ Mất kết nối Chrome Extension! Đã tạm dừng cào để bảo vệ tài khoản"*.
   - **Kiểm tra kết nối trước khi khởi chạy (`_execute_crawl_group_feed`)**: Nếu Extension chưa kết nối trước khi bắt đầu cào, hệ thống từ chối chạy ngay từ đầu kèm thông báo Toast và chỉ dẫn người dùng mở Chrome.
   - **Tối ưu hóa phân giải Group Slug (`_resolve_numeric_group_id`)**: Đảo thứ tự ưu tiên, sử dụng Extension Bridge để phân giải URL nhóm trước; nếu fallback sang `curl_cffi` thì tuyệt đối không gửi kèm cookie đăng nhập nhạy cảm.

2. **`frontend/src/hooks/useFacebook.ts` & `backend/proxify/ui/templates/facebook.html`**:
   - Cập nhật hàm lắng nghe trạng thái tiến độ `checkStatus()` / polling: Khi nhận được trường `toast_message` và `toast_icon` trong `group_crawl_state`, giao diện sẽ ngay lập tức bật Toast cảnh báo màu vàng/cam nổi bật trong 5 giây.

---

## 2. Mục đích & Ý nghĩa

- **Triệt tiêu nguyên nhân gây Checkpoint & Tự động Logout Facebook**:
  - Khi gửi request từ `curl_cffi` (Docker), Facebook phát hiện hành vi bất thường (khác IP, khác TLS handshake, thiếu cookie phân vùng CHIPS, lệch token `fb_dtsg`). Facebook kích hoạt cơ chế **Server-Side Session Revocation (Nghi vấn chiếm đoạt phiên)** và thu hồi quyền truy cập của tài khoản trên tất cả các thiết bị.
  - Việc loại bỏ fallback sang `curl_cffi` giúp bảo vệ an toàn 100% cho tài khoản Facebook của người dùng.
- **Trải nghiệm người dùng (UX) minh bạch, trực quan**:
  - Người dùng sẽ thấy thông báo Toast cảnh báo tức thì ngay trên màn hình nếu Chrome bị tắt hoặc Extension bị mất kết nối, thay vì thắc mắc tại sao tài khoản bị văng ra ngoài.

---

## 3. Mối liên hệ

- `backend/proxify/platforms/facebook/crawler.py` $\rightarrow$ `group_crawl_state`
- `backend/proxify/platforms/facebook/api.py` (`/api/facebook/crawl_status`)
- `frontend/src/hooks/useFacebook.ts` & `backend/proxify/ui/templates/facebook.html` (Hiển thị Toast & cập nhật trạng thái)
- `docs/codebase_guide/03_facebook_platform.md` (Cập nhật tài liệu kiến trúc)

---

## 4. Rủi ro & Edge Cases (Risks & Edge Cases)

- **Người dùng chưa bật Extension nhưng vẫn bấm cào**:
  - *Hành vi trước đây:* Hệ thống cố chạy bằng Docker $\rightarrow$ bị Facebook phát hiện và logout tài khoản.
  - *Hành vi hiện tại:* Hệ thống từ chối chạy, dừng an toàn và hiện Toast hướng dẫn: *"Chrome Extension chưa kết nối! Vui lòng mở Chrome có tab Facebook trước."*
- **Đứt mạng giữa chừng khi đang cào trang thứ $N$**:
  - Vòng lặp phân trang phát hiện cờ `is_disconnected = True` và lập tức `break`, bảo toàn toàn bộ dữ liệu của các trang đã cào trước đó vào cơ sở dữ liệu mà không làm hỏng phiên đăng nhập.
