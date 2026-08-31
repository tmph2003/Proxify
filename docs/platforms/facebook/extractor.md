# Tài liệu: Sửa lỗi đếm số lượng bài viết mới (Upsert vs Insert) trong Extractor

## Tóm tắt thay đổi
Đã chỉnh sửa phương thức `link_and_upsert` trong `proxify/platforms/facebook/extractor.py`:
- Bổ sung logic truy vấn trước danh sách các `post_id` và `comment_id` có trong batch đang được xử lý xem những ID nào đã tồn tại trong database.
- Cập nhật biến đếm: Thay vì đếm tổng số lượng post/comment được truyền vào hàm (`total_posts`, `total_comments`), giờ đây hàm chỉ tăng biến đếm (`new_posts`, `new_comments`) cho những bài viết/bình luận thực sự là **thêm mới** (chưa từng tồn tại trong CSDL và chưa từng được đếm trong cùng batch).

## Mục đích & Ý nghĩa
- **Vấn đề giải quyết:** Trước đây, khi crawler lấy về dữ liệu từ Facebook, nó truyền 1 danh sách các bài viết vào `link_and_upsert`. Hàm này đếm tổng số lượng phần tử của danh sách và trả về. Do thiết kế UPSERT, một số bài viết có thể đã tồn tại trong DB và chỉ được cập nhật (update) chứ không phải thêm mới (insert). Việc trả về tổng số khiến giao diện hiển thị thông báo "Đã thu thập 3 bài viết mới", nhưng thực tế trong cơ sở dữ liệu chỉ có 1 bài được thêm mới, làm sai lệch con số "Tổng số bài viết" và gây bối rối cho người dùng.
- **Ý nghĩa:** Trả về con số chính xác số lượng dữ liệu thực tế được **INSERT** vào cơ sở dữ liệu. Nhờ đó, thông báo dạng Toast (góc màn hình UI) sẽ khớp hoàn toàn với số lượng bài viết bị tăng thêm trên màn hình.

## Mối liên hệ
- Tệp bị ảnh hưởng: `proxify/platforms/facebook/extractor.py` (hàm `link_and_upsert`).
- Liên kết: Dữ liệu này được hàm `extract_from_responses` trả về, sau đó `crawler.py` nhận lấy và đưa vào `crawl_state.last_p_count` để truyền qua API `/api/facebook/crawl_status` cho UI hiển thị.

## Rủi ro (Risks & Edge Cases)
- **Hiệu năng (Performance):** Thay đổi này thêm 2 câu lệnh `SELECT ... = ANY(...)` vào database cho mỗi batch dữ liệu để kiểm tra sự tồn tại. Tuy nhiên, vì một trang Facebook trả về số lượng bài viết và bình luận không quá lớn (thường dưới 10-20 bài và một số lượng nhỏ bình luận trong một response JSON), câu lệnh này sử dụng Index trên Primary Key (`post_id`, `comment_id`) nên tốc độ thực thi rất nhanh (O(1) lookup trong DB), không gây nghẽn cổ chai.
- **Tính chính xác:** Sử dụng `set` để loại bỏ việc đếm trùng (trường hợp cùng 1 bài viết bị trả về 2 lần trong cùng 1 response JSON batch), đảm bảo con số trả về là chuẩn xác tuyệt đối.
