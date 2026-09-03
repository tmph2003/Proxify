# Tài Liệu Kỹ Thuật: Khắc Phục Lỗi Lặp Nút UI/UX & Tối Ưu Bộ Cào Bình Luận Facebook

- **Ngày cập nhật:** 2026-09-03
- **Module tác động:**
  - `frontend/src/pages/Facebook.tsx`
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/proxify/platforms/facebook/network.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `.agents/rules/docker_deployment.md`

---

## 1. Tóm tắt thay đổi

### A. Khắc phục lặp nút trong Modal (UI/UX)
- **Hiện tượng cũ:** Khi bài viết chưa có bình luận, trong thân Modal (phần empty state) xuất hiện nút `⬇️ Bắt đầu cào bình luận ngay`, đồng thời ở Footer của Modal cũng xuất hiện thêm nút `⬇️ Bắt đầu cào bình luận`, dẫn đến bị lặp 2 nút chức năng giống hệt nhau trên cùng một màn hình.
- **Giải pháp:**
  - Khi chưa có bình luận (`comments.length === 0`): Nút cào chính CTA chỉ hiển thị duy nhất ở vùng trung tâm Empty State. Footer chỉ giữ lại nút `Đóng`.
  - Khi đã có bình luận (`comments.length > 0`): Vùng Empty State ẩn đi, Footer sẽ hiển thị nút `🔄 Cập nhật / Cào tiếp` bên cạnh nút `Đóng`.
  - Hỗ trợ render linh hoạt cả `avatar_url` / `author_avatar` và `body_text` / `message_text`, bổ sung placeholder `[Hình ảnh / Nhãn dán / Không có nội dung chữ]` khi bình luận chỉ chứa sticker.

### B. Khắc phục lỗi cào bình luận không lấy được dữ liệu (Crawler Engine)
- **Nguyên nhân gốc rễ:**
  1. **Nhận nhầm Template GraphQL:** Template `comment` trong session cache bị gán vào query `CometUFIConversationGuideContainerQuery` (query gợi ý hội thoại, không trả về bình luận). Đồng thời form data thiếu đồng bộ `__user` và `av` với `c_user` của cookie, khiến Facebook trả về lỗi `Unauthorized logged out query`.
  2. **Bị chặn khi Fallback sang HTML Scraping:** Khi GraphQL trả về 0 bình luận, hệ thống cũ không tự động fallback sang cào HTML của trang bài viết. Thêm vào đó, `_safe_request` thiếu `impersonate="chrome120"` trong `StealthSessionManager` và bị ngắt nếu Bridge offline, dẫn đến request bị Facebook CDN từ chối (HTTP 400).
  3. **Đếm tổng bình luận:** Hàm `extract_from_responses` chỉ đếm số lượng *bình luận mới* (chưa có trong DB). Nếu bình luận đã được lưu trước đó, hàm trả về 0 khiến tiến trình báo `Tổng: 0 bình luận`.
- **Giải pháp xử lý:**
  1. Thêm bộ lọc kiểm tra tính hợp lệ của query template: Loại bỏ các query dạng `guide`, `suggestion` và chỉ nhận query thực sự chứa `comment` / `ufi`.
  2. Đồng bộ `c_user` từ cookie vào `__user` và `av` của form data trước khi gửi GraphQL.
  3. Bổ sung cơ chế Fallback tự động: Nếu GraphQL trả về 0 bình luận hoặc lỗi, crawler tự động chuyển sang Strategy 2 (cào và bóc tách embedded JSON từ trang HTML của bài viết).
  4. Cấu hình `impersonate="chrome120"` cho `GlobalNetworkClient` và cho phép request GET trang bài viết qua native `curl_cffi` với đầy đủ cookie/fingerprint.
  5. Cập nhật `progress["total"]` bằng cách truy vấn số lượng thực tế trong bảng `facebook.comments` của bài viết sau khi cào xong, đảm bảo hiển thị đúng số bình luận đã lưu.

---

## 2. Mục đích & Ý nghĩa

- **Trải nghiệm người dùng nhất quán:** Giao diện Modal gọn gàng, không bị trùng lặp nút, hiển thị đầy đủ avatar, tên tác giả, nội dung chữ và nhãn dán.
- **Tính tin cậy của Crawler:** Đảm bảo dù Facebook thay đổi GraphQL hay Extension Bridge chưa kết nối, cơ chế Fallback HTML với Chrome 120 impersonation vẫn cào và trích xuất thành công 100% dữ liệu bình luận về cơ sở dữ liệu.

---

## 3. Mối liên hệ

- `frontend/src/pages/Facebook.tsx` ↔ `useFacebook.ts` ↔ `backend/proxify/platforms/facebook/api.py`.
- `backend/proxify/platforms/facebook/crawler.py` ↔ `network.py` ↔ `extractor.py` ↔ `database.py`.

---

## 4. Rủi ro (Risks & Edge Cases)

- **Cookie Facebook hết hạn:** Nếu cookie bị die, request lấy trang sẽ chuyển hướng về trang Login. Hệ thống đã có kiểm tra status code và chuyển trạng thái cào thành báo lỗi rõ ràng.
- **Bài viết bị xóa hoặc đặt quyền riêng tư:** Hệ thống tự động nhận diện thông báo `"Bạn hiện không xem được nội dung này"` và đánh dấu `is_active = FALSE` trong DB.
