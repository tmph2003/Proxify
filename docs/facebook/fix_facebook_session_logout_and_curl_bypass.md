# Khắc phục lỗi Facebook bị Logout phiên đăng nhập (Bypass Python Direct Request & Safe Bridge Routing)

## Tóm tắt thay đổi
1. **`backend/proxify/platforms/facebook/api.py`**:
   - Loại bỏ hoàn toàn việc gọi hàm `fetch_fb_auth_tokens` (vốn sử dụng thư viện Python `curl_cffi` gửi request trực tiếp từ container Docker lên `facebook.com`).
   - Yêu cầu `fb_dtsg` phải được cấp an toàn thông qua Extension Chrome (môi trường trình duyệt thật), ngăn chặn việc Facebook phát hiện bot và hủy phiên đăng nhập của người dùng.
2. **`backend/proxify/platforms/facebook/crawler.py`**:
   - Chuyển đổi cơ chế phân giải slug nhóm (`_resolve_numeric_group_id`) từ request Python `manager.request` sang chạy thông qua **Extension Bridge** (`bridge.execute_request`).
3. **`backend/chrome_extension/popup.js`**:
   - Bắt buộc kiểm tra tab Facebook đang mở trước khi gửi dữ liệu. Nếu không tìm thấy tab Facebook hoặc không trích xuất được `fb_dtsg`, extension sẽ chặn gửi payload rỗng và hướng dẫn người dùng mở/F5 tab Facebook.
   - Bổ sung quét cookie chi tiết theo từng tên (`xs`, `c_user`, `sb`, `datr`, `fr`, `wd`) trên từng URL Facebook.

## Mục đích & Ý nghĩa
- **Giải quyết triệt để vấn đề bị Logout tài khoản Facebook**:
  - **Nguyên nhân cũ:** Trước đây, khi backend thiếu mã `fb_dtsg`, backend tự động dùng `curl_cffi` gửi request trực tiếp từ Docker lên Facebook kèm cookie của người dùng. Do request từ Python mang IP/TLS Fingerprint lạ và thiếu một số cookie bảo mật, Facebook lập tức đánh dấu phiên đăng nhập là bất thường (Session Hijacking) và **ép đăng xuất tài khoản trên toàn bộ thiết bị / trình duyệt**.
  - **Giải pháp:** Cấm hoàn toàn Python gửi request xác thực trực tiếp. 100% request đều được ủy quyền cho Extension Bridge thực hiện trên trình duyệt thật của người dùng.

## Mối liên hệ
- `backend/proxify/platforms/facebook/api.py` $\leftrightarrow$ `backend/chrome_extension/popup.js`: Đảm bảo chỉ khởi chạy crawler khi đã có đủ `fb_dtsg` từ tab thật.
- `backend/proxify/platforms/facebook/crawler.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py`: Định tuyến mọi tác vụ mạng qua Extension Bridge.

## Rủi ro (Risks & Edge Cases)
- **Người dùng cần đăng nhập lại Facebook 1 lần cuối** (do phiên trước đó đã bị Facebook ép logout bởi request Python cũ).
- **Cần Reload Extension**: Vào `chrome://extensions/` bấm **🔄 Tải lại (Reload)** để extension áp dụng code mới.
