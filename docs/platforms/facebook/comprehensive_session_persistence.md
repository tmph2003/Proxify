# Khởi Tạo & Đồng Bộ Toàn Diện Trạng Thái Theo Session (Session Persistence)

## 1. Tóm tắt thay đổi
* **Backend API (`backend/proxify/platforms/facebook/api.py`)**:
  * Cập nhật endpoint `GET /api/facebook/crawl_status` trả về thêm trường `comment_crawls: _default_crawler._comment_progress`.
  * Cho phép Frontend đồng bộ tức thì tiến trình cào bình luận của mọi bài viết ngay khi tải lại trang.
* **Frontend Hook `useFacebook.ts` (`frontend/src/hooks/useFacebook.ts`)**:
  * **Lưu trữ Session (`sessionStorage`)**:
    * `fb_is_crawling`: Cờ cào bảng tin nhóm Facebook (`crawling`).
    * `fb_is_feed_crawling`: Cờ tác vụ cào hàng loạt / refresh (`feedCrawling`).
    * `fb_statusText`, `fb_statusColor`: Nội dung & màu sắc thông báo tiến độ.
    * `fb_comment_progress`: Tiến độ cào bình luận chi tiết theo từng `post_id`.
    * `fb_page`, `fb_limit`: Số trang hiện tại và số bài viết mỗi trang.
    * `fb_sort`, `fb_order`: Cột và thứ tự sắp xếp (thời gian, bình luận, tương tác).
    * `fb_filterGroupId`, `fb_filterGroupName`, `fb_statusFilter`: Các bộ lọc nhóm và trạng thái bài viết.
    * `fb_selected_posts`: Danh sách ID bài viết được chọn bằng checkbox.
  * **Tự động khôi phục & Đồng bộ hai chiều**:
    * Khi mount trang (hoặc sau khi F5), đọc trực tiếp từ `sessionStorage` để UI không có độ trễ/giật.
    * Sau đó nhận payload từ API `/facebook/crawl_status` để hòa trộn (merge) với trạng thái thực tế từ server.
* **Frontend Page `Facebook.tsx` (`frontend/src/pages/Facebook.tsx`)**:
  * Lưu trạng thái mở Modal bình luận (`fb_modal_open`) và bài viết đang xem (`fb_selected_post`) vào `sessionStorage`.
  * Khi người dùng nhấn F5 trong lúc đang xem bình luận của một bài viết, modal tự động mở lại đúng bài viết đó và tải lại danh sách bình luận mượt mà.
  * Nút đóng modal dọn dẹp sạch state khỏi `sessionStorage`.

---

## 2. Mục đích & Ý nghĩa
* **Giải quyết triệt để yêu cầu:** "kể cả khi crawl các thứ nhé, hãy lưu lại state theo session nhé".
* Trước đây, khi người dùng thực hiện các thao tác:
  1. Cào bình luận cho một hoặc nhiều bài viết.
  2. Thực hiện làm mới hàng loạt (Bulk Refresh).
  3. Chọn 10 bài viết để chuẩn bị xuất CSV hoặc xóa.
  4. Đang phân trang ở trang 4 hoặc lọc theo nhóm X.
  5. Đang mở xem bình luận chi tiết trong Modal.
  $\rightarrow$ Chỉ cần vô tình bấm F5 (hoặc trình duyệt reload), toàn bộ lựa chọn, tiến trình hiển thị spinner và dữ liệu trang đều bị reset về trạng thái ban đầu.
* Với kiến trúc Session Persistence toàn diện, mọi tác vụ đang chạy hay trạng thái lọc/chọn đều được bảo toàn nguyên vẹn xuyên suốt phiên duyệt web của tab.

---

## 3. Mối liên hệ
* `backend/proxify/platforms/facebook/api.py`: Cung cấp nguồn dữ liệu chân thực (Single Source of Truth) từ Backend.
* `frontend/src/hooks/useFacebook.ts`: Lớp tầng dữ liệu trung gian kết nối State, Storage và Polling.
* `frontend/src/pages/Facebook.tsx`: Lớp View hiển thị phản hồi tức thì người dùng.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Dữ liệu mồ côi trong Session**: Nếu một tác vụ cào bình luận bị crash đột ngột ở phía server trong lúc người dùng reload, frontend vẫn có thể hiển thị tiến trình cũ trong chốc lát cho đến khi polling tiếp theo nhận trạng thái `error`/`idle` từ backend để tự động dọn dẹp.
