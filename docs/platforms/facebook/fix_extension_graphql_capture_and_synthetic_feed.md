# Khắc Phục Lỗi Extension Chưa Bắt Được Gói Tin GraphQL & Cơ Chế Tự Động Tổng Hợp Feed (Autonomous Synthetic Feed)

## 1. Tóm Tắt Thay Đổi
1. **Sửa Lỗi Proxy RAM `_TenantDictProxy` (`auth.py` & `api.py`)**:
   - Khắc phục lỗi chí mạng khiến `_TenantTemplateProxy` và `_TenantCookieProxy` luôn trả về `len() == 0` và `bool() == False`. Do kế thừa từ `dict` mà không cài đặt `__len__`, `__bool__`, `__iter__`, câu lệnh `if IN_MEMORY_TEMPLATES:` trong `get_saved_tokens()` luôn luôn đánh giá thành `False`, khiến Backend luôn báo "không tìm thấy template" dù Extension đã gửi template thành công nhiều lần.
   - Hợp nhất thành class `_TenantDictProxy` đầy đủ các phương thức dunder (`__len__`, `__bool__`, `__iter__`, `__repr__`, `__eq__`), hỗ trợ lưu trữ phân tách nhiều tenant theo `client_id`.
   - Nâng cấp hàm `get_saved_tokens(client_id="default")` để tự động ưu tiên lấy template theo đúng `client_id` của client đang gọi.
2. **Cơ Chế Tự Động Tổng Hợp Feed Template (`_synthesize_feed_template` trong `crawler.py`)**:
   - Bổ sung phương thức `_synthesize_feed_template(group_id, raw_cookie, client_id)`.
   - Nếu bộ nhớ RAM chưa bắt được gói tin `feed_tpl` (do người dùng chỉ lướt lướt đầu trang nhóm mà Facebook render tĩnh bằng HTML SSR chưa gọi GraphQL, hoặc người dùng chỉ mới bấm "Lấy Cookie & Token" trên Extension popup), hệ thống sẽ tự động tổng hợp một template `GroupsCometFeedRegularStoriesPaginationQuery` hoàn chỉnh từ lịch sử bảng `requests` hoặc từ baseline chuẩn (`doc_id: 38367899859521393`).
   - Tự động nhúng `fb_dtsg`, `lsd`, `__user`, `sd` từ `TENANT_COOKIES[client_id]` và gán `variables: {"id": group_id, "sortingSetting": "CHRONOLOGICAL"}`.
   - Gọi pre-synthesis ngay khi Extension popup bắn cookie/token vào `/api/facebook/cookie`, giúp hệ thống sẵn sàng cào ngay lập tức mà không cần người dùng phải cuộn chuột tìm bắt gói tin thủ công.
3. **Sửa Lỗi Import Cookie Fallback (`crawler.py`)**:
   - Sửa lỗi `from proxify.platforms.facebook.auth import IN_MEMORY_COOKIES` bị lỗi `ImportError` ngầm khiến hàm `_resolve_cookie` không lấy được cookie đã lưu trên RAM.
   - Chuyển `TENANT_COOKIES` và `IN_MEMORY_COOKIES` vào `auth.py` và import đồng bộ cho cả `api.py` và `crawler.py`.
4. **Nâng Cấp WebRequest Listener trong Extension (`background.js`)**:
   - Mở rộng mẫu URL từ `.../api/graphql/*` thành `.../api/graphql*` để bắt trọn vẹn cả các request không có dấu gạch chéo ở cuối hoặc chứa query params.
   - Bổ sung bộ phân tích `multipart/form-data` qua regex trong `details.requestBody.raw`, đảm bảo không bị mất tham số `fb_api_req_friendly_name` hay `doc_id` khi Facebook gửi form multipart.
   - Tự động bóc tách `friendlyName` từ query parameters hoặc gán fallback `GraphQL_doc_<doc_id>`.

---

## 2. Mục Đích & Ý Nghĩa
- **Giải quyết triệt để thông báo lỗi**:
  ```
  ❌ Extension chưa bắt được gói tin GraphQL thực.
  ⚠️ Hướng dẫn khắc phục:
  1. Vui lòng mở Facebook trong trình duyệt.
  2. Truy cập vào MỘT NHÓM FACEBOOK BẤT KỲ.
  3. Cuộn chuột lướt xuống vài bài viết để Extension tự động bắt gói dữ liệu.
  ```
  Người dùng dù đã lướt Facebook thật nhưng hệ thống vẫn liên tục báo lỗi này do `get_saved_tokens()` trả về `None` (lỗi `bool(_TenantTemplateProxy) == False`).
- **Nâng cao trải nghiệm người dùng (Zero-Friction Crawling)**: Người dùng chỉ cần mở Facebook và bấm "Lấy Cookie & Token" trên Extension hoặc paste cookie. Hệ thống tự động chuẩn bị template mà không bắt buộc người dùng phải canh đúng khoảnh khắc cuộn chuột để bắt API ngầm.
- **Tuân thủ Clean Architecture**: Quy tụ toàn bộ quản lý state cookie/token in-memory về đúng module `auth.py`, phân định rõ ràng giữa tầng lưu trữ dữ liệu xác thực (Domain/Infrastructure) và tầng điều phối cào dữ liệu (`crawler.py`).

---

## 3. Mối Liên Hệ
- `backend/proxify/platforms/facebook/auth.py`: Quản lý kho lưu trữ đa phiên `TENANT_TEMPLATES`, `TENANT_COOKIES` và cung cấp `_TenantDictProxy`.
- `backend/proxify/platforms/facebook/api.py`: Nhận cookie/template từ Extension popup và endpoint `/api/facebook/cookie`, kích hoạt `_synthesize_feed_template` đón đầu.
- `backend/proxify/platforms/facebook/crawler.py`: Tiêu thụ `feed_tpl`, `comment_tpl`, cookie để thực thi truy vấn GraphQL cào bài viết theo thời gian thực.
- `backend/chrome_extension/background.js`: Lắng nghe webRequest trên tab Chrome thật để ghi nhận các template mới nhất khi Facebook cập nhật cấu trúc Relay.
- `backend/tests/test_crawler_synthetic_feed.py`: Bộ kiểm thử tự động xác minh tính đúng đắn của proxy class và khả năng tự tổng hợp feed template.

---

## 4. Rủi Ro & Biên Độ Ngoại Lệ (Risks & Edge Cases)
1. **Facebook thay đổi `doc_id` của GroupsCometFeed**:
   - *Rủi ro*: Nếu Facebook cập nhật `doc_id` mới trên toàn cầu và DB chưa lưu request mới nào, `doc_id` cứng của synthetic baseline có thể trả về lỗi `Query ID not found`.
   - *Biện pháp giảm thiểu*: Cơ chế đa tầng ưu tiên đọc `doc_id` từ request gần nhất trong bảng `requests` của PostgreSQL, đồng thời nếu Extension bắt được gói tin mới khi người dùng lướt web thì sẽ tự động ghi đè lên template tổng hợp.
2. **Tab Extension cần được tải lại (Reload)**:
   - Do có thay đổi trong `background.js`, nếu người dùng muốn Extension tự động bắt các gói tin multipart theo URL pattern mới, người dùng nên vào `chrome://extensions/` và bấm nút **Tải lại (Reload)** trên Extension Proxify. Tuy nhiên, nhờ có `_synthesize_feed_template`, hệ thống vẫn hoạt động bình thường ngay cả khi Extension chưa reload.
