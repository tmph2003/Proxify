# Khắc phục lỗi Facebook bắt đăng nhập dù Extension đã lấy Cookie (Error 1357001)

## Tóm tắt thay đổi
1. **`backend/chrome_extension/background.js`**:
   - Thêm cấu hình `credentials: "include"` và `mode: "cors"` vào hàm `fetch` trong `executeBridgeJob`. Điều này đảm bảo toàn bộ Cookie thật của người dùng trên trình duyệt (bao gồm `c_user`, `xs`, `sb`, `datr`, v.v.) được đính kèm vào GraphQL request gửi đến `https://www.facebook.com/api/graphql/`.
2. **`backend/chrome_extension/popup.js`**:
   - Nâng cấp cơ chế trích xuất `fb_dtsg` và `lsd` với 4 tầng fallback liên tiếp (`DTSGInitialData`, `DTSGInitData`, input DOM `name="fb_dtsg"`, và regex HTML).
   - Bổ sung thông báo trạng thái rõ ràng, phân biệt giữa trường hợp đã lấy đủ `Cookie + fb_dtsg` và trường hợp thiếu `fb_dtsg` để hướng dẫn người dùng F5 tab Facebook.
3. **`backend/proxify/platforms/facebook/api.py`**:
   - Cập nhật hàm `_bg_check_status` để lấy `active_cookie` và `user_agent` từ `IN_MEMORY_COOKIES` thay vì truyền `cookies = {}` rỗng, ngăn chặn việc Facebook điều hướng sang trang login khi kiểm tra trạng thái bài viết.

## Mục đích & Ý nghĩa
- **Khắc phục triệt để lỗi 1357001 (Please log in to continue)**: Do Extension Service Worker gọi `fetch()` cross-origin tới Facebook mà không có `credentials: "include"`, khiến request gửi đi hoàn toàn không có Cookie xác thực.
- **Tránh việc Backend gọi curl_cffi gây Checkpoint / Login Redirect**: Khi popup Extension lấy được chính xác `fb_dtsg` từ tab Facebook thật, Backend không cần phải tự gửi request từ Python để lấy token nữa, tránh được sự sai lệch về TLS Fingerprint.

## Mối liên hệ
- `backend/chrome_extension/background.js` $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/crawler.py`: Luồng thực thi request GraphQL trung gian qua Extension Bridge.
- `backend/chrome_extension/popup.js` $\leftrightarrow$ `backend/proxify/platforms/facebook/api.py`: Đồng bộ Cookie, `fb_dtsg`, và User-Agent vào bộ nhớ RAM (`IN_MEMORY_COOKIES`).

## Rủi ro (Risks & Edge Cases)
- **Extension cần được Reload**: Người dùng sau khi sửa file Extension cần vào `chrome://extensions` và bấm nút **Tải lại (Reload)** Extension để code mới có hiệu lực trong Service Worker.
- **Yêu cầu mở tab Facebook thật**: Nếu người dùng không mở bất kỳ tab Facebook nào trong trình duyệt lúc bấm Extension Popup, mã `fb_dtsg` sẽ không lấy được qua DOM/JS context. Popup đã được cập nhật để hiển thị cảnh báo hướng dẫn người dùng mở tab Facebook và bấm lại.
