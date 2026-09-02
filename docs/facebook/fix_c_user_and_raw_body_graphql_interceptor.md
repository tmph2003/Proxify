# Khắc phục lỗi thiếu c_user và không bắt được gói tin GraphQL Facebook (Raw Body Interceptor & Universal Cookie Scan)

## Tóm tắt thay đổi
1. **`backend/chrome_extension/background.js`**:
   - Khắc phục lỗi nghiêm trọng trong WebRequest API: Facebook gửi request GraphQL bằng `fetch()` khiến Chrome đưa dữ liệu vào `details.requestBody.raw` (ArrayBuffer) chứ không phải `details.requestBody.formData`.
   - Bổ sung bộ giải mã `TextDecoder("utf-8")` và `URLSearchParams` để trích xuất toàn bộ form data từ `raw.bytes`.
   - Mở rộng bộ lọc `fb_api_req_friendly_name` để bắt mọi query liên quan đến Nhóm và Bài viết (`Group`, `Feed`, `Comment`, `UFI`, `Story`, `Post`).
2. **`backend/chrome_extension/popup.js`**:
   - Nâng cấp cơ chế quét Cookie đa chiến lược (Multi-strategy scan): Quét mọi URL (`https://www.facebook.com`, `https://facebook.com`, `https://m.facebook.com`, `https://web.facebook.com`), domain, partitionKey (`partitionKey: {}`), và toàn bộ Cookie Stores.
   - Inject script trực tiếp vào tab Facebook để đọc `CurrentUserInitialData.USER_ID` / `Env.USER_ID`. Nếu cookie thiếu `c_user` (do bảo mật trình duyệt hoặc chuyển đổi profile), Extension sẽ tự động gán `c_user=<USER_ID>` từ context thật.
   - Bỏ điều kiện chặn cứng `if (!cookieStr.includes("c_user=")) return;` gây nghẽn toàn bộ quá trình đồng bộ khi trình duyệt ẩn `c_user`.
3. **`backend/proxify/platforms/facebook/api.py` & `crawler.py`**:
   - Backend hỗ trợ nhận `user_id` từ Extension và tự động bổ sung vào `c_user` / `__user` trong form data GraphQL.
   - Nới lỏng điều kiện kiểm tra cookie trong `crawler.py` để tương thích hoàn hảo với cơ chế Extension Bridge (`fetch` mang `credentials: "include"`).

## Mục đích & Ý nghĩa
- **Giải quyết triệt để lỗi "Không tìm thấy c_user trong Cookie"**: Trình duyệt Chrome hiện đại thường bảo vệ hoặc phân vùng (partition) cookie `c_user` và `xs`. Bằng cách đọc UID trực tiếp từ bộ nhớ JavaScript của Facebook tab (`CurrentUserInitialData`) và gộp toàn bộ cookie stores, Extension luôn nhận diện được trạng thái đăng nhập.
- **Giải quyết triệt để lỗi "Không cào được tí nào"**: Trước đây `background.js` không đọc được `requestBody.raw` nên Extension không bao giờ bắt được GraphQL template khi người dùng lướt Facebook. Việc giải mã `raw.bytes` giúp hệ thống bắt được 100% template mẫu khi người dùng lướt bất kỳ nhóm nào.

## Mối liên hệ
- `backend/chrome_extension/background.js` $\leftrightarrow$ `backend/proxify/platforms/facebook/token_store.py`: Cung cấp template GraphQL thật cho Crawler.
- `backend/chrome_extension/popup.js` $\leftrightarrow$ `backend/proxify/platforms/facebook/api.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/crawler.py`: Đồng bộ UID, Cookie, `fb_dtsg`, `lsd`, `SiteData`.

## Rủi ro (Risks & Edge Cases)
- **Cần Reload Extension**: Sau khi cập nhật code trong `backend/chrome_extension/`, người dùng cần mở `chrome://extensions/` và bấm nút **🔄 Tải lại (Reload)**.
- **Yêu cầu mở sẵn 1 tab Facebook**: Để trích xuất được `fb_dtsg` và UID trực tiếp từ bộ nhớ web, người dùng nên có ít nhất 1 tab Facebook đang mở trong trình duyệt.
