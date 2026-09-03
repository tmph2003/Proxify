# Tính Năng Nhấn Nút Để Dừng Cào Bình Luận (Stop Comment Crawl Toggle)

## 1. Tóm tắt thay đổi
* **Backend (`crawler.py`, `api.py`)**:
  * Thêm thuộc tính `self._stopped_comment_posts: set[str]` vào `FacebookCrawler`.
  * Thêm phương thức `stop_comment_crawling(self, post_id: Optional[str] = None)` cho phép hủy ngay lập tức tiến trình cào bình luận của một bài viết cụ thể hoặc toàn bộ bài viết.
  * Trong vòng lặp phân trang GraphQL của `_execute_crawl_comments`, kiểm tra `str(post_id) in self._stopped_comment_posts` trước mỗi request trang. Khi phát hiện cờ dừng, vòng lặp ngắt ngay tức khắc (`break`), lưu lại số bình luận đã cào được và cập nhật trạng thái `idle`.
  * Thêm endpoint API: `POST /api/facebook/stop_comment_crawl` (nhận `{ post_id: "..." }`).
* **Frontend (`useFacebook.ts`, `Facebook.tsx`)**:
  * `useFacebook.ts`: Cung cấp hàm `stopCommentCrawl(postId: string)` gọi API dừng và cập nhật trạng thái session.
  * `Facebook.tsx`:
    * **Tại bảng bài viết (Table Row)**: Khi bài viết đang cào bình luận, nút hiển thị chuyển thành nút dừng đỏ `🛑 Dừng ({số_lượng})` kèm spinner. **Người dùng nhấn lại vào nút này là tiến trình cào sẽ DỪNG NGAY LẬP TỨC**. Kèm theo nút icon `👁️` bên cạnh để mở modal xem bình luận đã tải nếu muốn.
    * **Tại Modal bình luận**: Cả ở trạng thái trống (empty state) và footer bên dưới, khi đang cào bình luận, nút hành động tự động chuyển thành nút đỏ **`🛑 Dừng lấy bình luận`**. Nhấn vào sẽ dừng ngay.

---

## 2. Mục đích & Ý nghĩa
* **Giải quyết yêu cầu của người dùng:** "tôi muốn dừng lấy comment thì click lại vào button".
* Mang lại trải nghiệm chuyển đổi trạng thái hai chiều (Toggle Switch) trực quan:
  * Click lần 1: Bắt đầu cào bình luận.
  * Click lần 2: Dừng cào bình luận ngay tại trang hiện tại.
* Dữ liệu các bình luận đã tải về trước thời điểm dừng vẫn được giữ nguyên vẹn trong Database PostgreSQL mà không bị mất.

---

## 3. Mối liên hệ
* `backend/proxify/platforms/facebook/crawler.py`: Điều phối vòng lặp và xử lý cờ ngắt `_stopped_comment_posts`.
* `backend/proxify/platforms/facebook/api.py`: Tiếp nhận request dừng từ HTTP endpoint `/facebook/stop_comment_crawl`.
* `frontend/src/hooks/useFacebook.ts`: Quản lý state và gọi API dừng.
* `frontend/src/pages/Facebook.tsx`: Giao diện Toggle button ở bảng và trong popup modal.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Request đang gửi dở**: Nếu người dùng nhấn Dừng đúng lúc request GraphQL đang bay trên mạng, server sẽ hoàn tất nốt trang đó vào DB rồi mới dừng, đảm bảo tính toàn vẹn của dữ liệu và không gây lỗi parse JSON.
