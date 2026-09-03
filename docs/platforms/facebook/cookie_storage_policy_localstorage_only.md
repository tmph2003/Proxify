# Chính Sách Bảo Mật: Lưu Trữ Cookie Trên LocalStorage & Extractor Chỉ Đọc Dữ Liệu

## 1. Tóm tắt thay đổi

1. **`backend/proxify/platforms/facebook/token_store.py`**:
   - Xóa bỏ hoàn toàn hằng số `SESSION_CACHE_FILE` và mọi thao tác `open()` ghi/đọc file đĩa.
   - Chuyển `save_session_cache()` và `load_session_cache()` thành hàm no-op (`pass`). Hệ thống vận hành thuần bộ nhớ RAM (`IN_MEMORY_TEMPLATES` và `IN_MEMORY_COOKIES`).
2. **Xóa bỏ tệp đĩa `backend/fb_session_cache.json`**:
   - Tệp này đã bị xóa vĩnh viễn khỏi repo và container. Không còn bất kỳ file đĩa nào lưu trữ cache phiên hay cookie.
3. **`backend/proxify/platforms/facebook/api.py`**:
   - Xóa hoàn toàn lệnh gọi `save_session_cache()`. Endpoint `/api/facebook/cookie` chỉ giữ dữ liệu trong RAM tạm thời.
4. **`frontend/src/hooks/useFacebook.ts`**:
   - Sửa hàm `startCrawl()`: Đọc trực tiếp từ `activeCookie = cookie || localStorage.getItem('fb_cookie') || ''` và truyền qua tham số payload `cookie` khi gọi API `/api/facebook/crawl`.
   - Đảm bảo cookie chỉ lưu duy nhất ở `localStorage` của trình duyệt người dùng với key `'fb_cookie'`.
5. **Cập nhật tài liệu cẩm nang**:
   - Sửa `docs/codebase_guide/04_chrome_extension.md` (sơ đồ ASCII & Mermaid).
   - Sửa `docs/codebase_guide/03_facebook_platform.md` (mục `token_store.py` & `api.py`).
   - Sửa `docs/PROJECT_EXPLANATION.md` (xóa tệp `fb_session_cache.json` khỏi cấu trúc dự án).

---

## 2. Mục đích & Ý nghĩa

- **An toàn tuyệt đối cho tài khoản (Zero-Persistence on Disk/DB):**
  - Cookie đăng nhập là thông tin nhạy cảm nhất của phiên Facebook (chứa `c_user`, `xs`, `fr`, `datr`).
  - Nếu lưu cookie vào file (`fb_session_cache.json`) hoặc lưu vào cơ sở dữ liệu (`PostgreSQL`), cookie có nguy cơ bị lộ khi commit mã nguồn, sao lưu database hoặc bị quét qua container.
  - Áp dụng nguyên tắc **Chỉ lưu ở `localStorage` của Client**: Phía backend và Extractor chỉ đóng vai trò nhận vào RAM lúc bắt đầu cào và giải phóng khỏi RAM khi phiên kết thúc, không ghi vết ra bất kỳ phương tiện lưu trữ lâu dài nào.

---

## 3. Mối liên hệ

- **`frontend/src/hooks/useFacebook.ts`** & **`backend/proxify/ui/templates/facebook.html`**: Lưu trữ cookie ở `localStorage.getItem('fb_cookie')` và gửi lên API khi kích hoạt tác vụ.
- **`backend/proxify/platforms/facebook/api.py`**: Nhận `cookie` qua endpoint `/api/facebook/crawl` và `/api/facebook/cookie`, lưu tạm trong RAM `IN_MEMORY_COOKIES`.
- **`backend/proxify/platforms/facebook/token_store.py`**: Quản lý template GraphQL đệm, lọc bỏ sạch cookie trước khi ghi file đĩa.
- **`backend/proxify/platforms/facebook/crawler.py`**: Nhận cookie từ bộ nhớ RAM để gửi kèm request cào In-Tab qua Extension.

---

## 4. Rủi ro & Trường hợp ngoại lệ (Risks & Edge Cases)

- **Người dùng xóa cache trình duyệt hoặc mở bằng tab ẩn danh (Incognito):**
  - `localStorage` của tab ẩn danh sẽ trống. Giao diện sẽ phát hiện chưa có cookie và hiển thị thông báo: *"Vui lòng nhập cookie Facebook trước!"* hoặc người dùng chỉ cần click *"Lấy & Lưu Cookie"* trên Extension Popup để nạp lại vào `localStorage` trong 1 giây.
- **Restart Container Docker / Server:**
  - Vì cookie không lưu ra đĩa, khi restart container, backend sẽ không còn cookie cũ trong RAM. Tuy nhiên, ngay khi người dùng mở Dashboard trên trình duyệt, hook React sẽ tự động lấy cookie từ `localStorage` để gửi vào backend, đảm bảo hệ thống tiếp tục hoạt động trơn tru mà không làm lộ cookie ra đĩa.
