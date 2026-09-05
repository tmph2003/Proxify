# Tài liệu: Khắc phục Triệt để Checkpoint Facebook & Sửa Lỗi Nút "Làm mới" (Refresh Button)

## 1. Tóm tắt thay đổi

1. **Thiết lập Hard Guardrail cho Extension Bridge (`bridge.py` & `background.js`):**
   - Nghiêm cấm tuyệt đối việc gọi `bridge.execute_request` với URL HTML (chẳng hạn permalink bài viết `/groups/.../posts/...` hay URL nhóm `/groups/...`).
   - `bridge.execute_request` tại backend và function thực thi trong tab tại Extension Service Worker kiểm tra URL: nếu không chứa `/api/graphql/`, từ chối ngay lập tức với HTTP 403.
   
2. **Loại bỏ việc cào HTML có cookie trong tab (`_resolve_numeric_group_id` & `check_status`):**
   - Trong `_resolve_numeric_group_id`: Xóa bỏ đoạn mã gửi request qua tab bridge. Thay bằng đọc DB cache, nếu chưa có thì gửi request ẩn danh qua `curl_cffi` (impersonate `chrome120`) **HOÀN TOÀN KHÔNG MANG COOKIE**.
   - Trong `check_status`: Chuyển sang dùng `crawler.refresh_single_post` (truy vấn GraphQL an toàn) hoặc kiểm tra ẩn danh không cookie.

3. **Thiết kế lại Cơ chế Làm Mới Bài Viết (`refresh_single_post` & `_execute_crawl_specific_posts`):**
   - Viết mới hàm `FacebookCrawler.refresh_single_post`: Sử dụng GraphQL query `CommentsListComponentsPaginationQuery` thông qua `_safe_request` (POST tới `/api/graphql/`).
   - Phân tích GraphQL response bằng `DataHelper.find_key` để lấy số lượng reaction (`reaction_count`), số lượng comment (`total_comment_count`), `feedback_id`, và cập nhật trạng thái `is_active` cùng thời gian `updated_at`.
   - Thay thế toàn bộ logic cũ trong `_execute_crawl_specific_posts` (vốn gửi GET HTML tới permalink gây dính checkpoint và regex sai).

4. **Sửa lỗi Nút "Làm mới" (Refresh) trên Giao diện (`api.py`, `useFacebook.ts`, `Facebook.tsx`):**
   - **Backend (`api.py`):** Xử lý `action == "refresh"` trong `_handle_bulk_action` hiện đã sinh `task_id`, trả về `{ status: "ok", task_id: task_id }`, và cập nhật tiến trình vào `self._bulk_progress[task_id]`.
   - **Frontend Hook (`useFacebook.ts`):** 
     - Nhận `task_id`, polling `/api/facebook/bulk_status?task_id=...` hiển thị toast tiến trình trực quan (`Đang làm mới 1/3...` -> `Hoàn tất làm mới 3/3 bài viết`).
     - Tự động gọi `loadData()` để cập nhật số liệu bảng sau khi hoàn tất.
     - Thêm hàm `refreshSinglePost(postId)` để hỗ trợ làm mới từng bài riêng lẻ.
   - **UI Component (`Facebook.tsx`):**
     - Nút "🔄 Làm mới" trên Floating Action Bar được gắn trạng thái `disabled={feedCrawling}` và nhãn `⏳ Đang làm mới...`.
     - Thêm nút "🔄 Tải lại bảng" tại thanh tiêu đề bảng dữ liệu để người dùng có thể tải lại dữ liệu từ Postgres bất kỳ lúc nào.
     - Thêm nút icon 🔄 nhỏ ngay tại cột "Tương tác" của mỗi bài viết để người dùng có thể làm mới riêng lẻ 1 bài viết chỉ với 1 click.

---

## 2. Mục đích & Ý nghĩa

### Vấn đề 1: Checkpoint Facebook (Tài khoản bị khóa/bắt xác minh danh tính)
- **Nguyên nhân gốc rễ:** Khi người dùng bấm "Làm mới" hoặc "Kiểm tra", hệ thống trước đây gửi lệnh qua Extension Bridge để thực thi `window.fetch(permalink_url, {credentials: 'include'})` trực tiếp trong tab Facebook đang đăng nhập. Trình duyệt Chrome phát ra request với header `Sec-Fetch-Dest: empty` và `Sec-Fetch-Mode: cors` nhắm vào URL tài liệu HTML. Hệ thống chống cào dữ liệu của Meta (Edge Bot Detection) nhận diện ngay đây là hành vi dùng script/extension cào HTML có cookie đăng nhập, lập tức đánh dấu tài khoản bị xâm nhập và áp đặt Checkpoint.
- **Ý nghĩa giải pháp:** Facebook web chính thức (React Comet SPA) **chỉ** gọi GraphQL API (`/api/graphql/`) khi tương tác, không bao giờ gọi `fetch()` trang HTML. Việc giới hạn Bridge chỉ chạy `/api/graphql/` và đưa mọi tác vụ đọc HTML ra ngoài backend bằng `curl_cffi` ẩn danh (không cookie) loại trừ 100% rủi ro checkpoint cho tài khoản người dùng.

### Vấn đề 2: Nút "Làm mới" không hoạt động
- **Nguyên nhân gốc rễ:** Backend trả về kết quả không có `task_id`, khiến frontend hiểu nhầm là tác vụ đã xong ngay lập tức trong 0 giây, tự động tắt loading và xóa lựa chọn bài viết trước khi tác vụ ngầm kịp chạy. Ở phía sau, tác vụ ngầm lại dùng regex HTML để tìm like/comment (vốn đã lỗi thời với Facebook Comet) nên số liệu không bao giờ cập nhật.
- **Ý nghĩa giải pháp:** Chuẩn hóa luồng `task_id` -> polling -> `_bulk_progress` -> `loadData()`. Dữ liệu tương tác được lấy chính xác từ Relay Node GraphQL, phản ánh live ngay lên giao diện.

---

## 3. Mối liên hệ (Dependencies & Impact)

- **`proxify.platforms.facebook.bridge` (`bridge.py`):**
  - Đóng vai trò chốt chặn an ninh vòng ngoài: Chặn đứng mọi request non-GraphQL trước khi gửi tới Extension queue.
- **`backend/chrome_extension/background.js`:**
  - Đóng vai trò chốt chặn an ninh vòng trong (Defense-in-depth): Từ chối thực thi bất kỳ URL nào không phải GraphQL trong tab.
- **`proxify.platforms.facebook.crawler` (`crawler.py`):**
  - Cung cấp `refresh_single_post`, `_synthesize_comment_template`, và `_parse_metrics_from_graphql`.
  - Liên kết trực tiếp với bảng `facebook.posts` trong PostgreSQL để lưu `reaction_count`, `comment_count`, `feedback_id`, `is_active`, `updated_at`.
- **`proxify.platforms.facebook.api` (`api.py`):**
  - Điều phối `_handle_bulk_action` và cập nhật tiến trình vào `_bulk_progress` cho endpoint `_handle_bulk_status`.
- **Frontend (`useFacebook.ts`, `Facebook.tsx`):**
  - Tiêu thụ `task_id`, hiển thị Toast Notification, vô hiệu hóa nút bấm khi đang bận và tự động reload bảng dữ liệu.

---

## 4. Rủi ro & Edge Cases (Risks & Edge Cases)

1. **Trường hợp bài viết trong Nhóm Kín (Private Group) khi chưa có cookie GraphQL:**
   - Nếu tài khoản chưa bắt được GraphQL template (chưa mở trang nhóm trong trình duyệt) và bridge không kết nối, việc gọi GraphQL sẽ thất bại.
   - Khi đó fallback ẩn danh (không cookie) vào bài viết nhóm kín sẽ bị Facebook chuyển hướng sang `login.php`.
   - *Biện pháp đã xử lý:* Mã nguồn nhận biết `login.php` và không vội vàng đánh dấu `is_active = FALSE` mà giữ nguyên trạng thái cũ, tránh false negative.
2. **Tốc độ làm mới số lượng lớn bài viết:**
   - Nếu người dùng chọn hàng trăm bài viết và bấm "Làm mới", việc gửi quá dồn dập có thể khiến Facebook tạm thời rate-limit GraphQL.
   - *Biện pháp đã xử lý:* Đã thêm độ trễ nghỉ 1.5s giữa các bài viết và chạy tuần tự để tôn trọng giới hạn tải và bảo đảm an toàn cho tài khoản.
3. **Bài viết không có `feedback_id` trong DB:**
   - *Biện pháp đã xử lý:* Hệ thống tự động mã hóa Base64 theo chuẩn Facebook Relay Node: `base64(f"feedback:{canonical_post_id}")` để sinh ra `target_fbid` hợp lệ.
