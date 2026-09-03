# Tài liệu Kỹ thuật: Khắc phục Hiện tượng Trùng lặp Bài viết (Duplicate Posts) & Cơ chế Chuẩn hóa Canonical Post ID

## Tóm tắt thay đổi

1. **`backend/proxify/platforms/facebook/extractor.py`**:
   - Thêm phương thức `DataHelper.extract_canonical_post_id()`: Tự động chuẩn hóa mọi dạng mã ID bài viết của Facebook về ID số chuẩn duy nhất (Canonical Numeric ID):
     - Dạng 1: `UzpfSTYx...` (Story ID tĩnh, chứa mã `:VK:{ID}`).
     - Dạng 2: `UzpfSUZTOjE6...` (Mã con trỏ luồng đệm Infinite Feed Stream do Facebook Comet sinh ra khi cuộn trang hoặc phân trang).
     - Dạng 3: `feedback_id` (Base64 chứa `feedback:{numeric_id}`).
     - Dạng 4: `permalink_url` (Chứa `/posts/{numeric_id}/`).
   - Cập nhật `PostExtractor.extract()`: Mọi bài viết sau khi bóc tách đều được chuẩn hóa `post_id` về ID số duy nhất này trước khi trả về.
2. **`backend/proxify/platforms/facebook/repository.py`**:
   - Cập nhật `PostRepository._do_upsert()`: Kiểm tra và chuẩn hóa `canonical_pid` trước khi thực thi câu lệnh SQL:
     ```sql
     INSERT INTO facebook.posts (...) VALUES (...)
     ON CONFLICT (post_id) DO UPDATE SET ...
     ```
3. **Database Migration & Dọn dẹp bản ghi cũ**:
   - Đã chạy kịch bản gom cụm và dọn dẹp các bản ghi trùng lặp cũ trong PostgreSQL (`facebook.posts`):
     - Bài viết của tác giả "Linh Trần" (`1432819905416474`) đã được gộp từ 2 bản ghi thành 1 bản ghi duy nhất, bảo toàn tương tác mới nhất (`reaction_count = 3`, `updated_at = 09:18:39`).
     - Bài viết của tác giả "Mai Anh" (`1432763315422133`) đã được gộp thành 1 bản ghi duy nhất.

---

## Mục đích & Ý nghĩa

- **Nguyên nhân gốc rễ**: Facebook Comet sinh ra nhiều dạng ID cho cùng 1 bài viết tùy theo cách lấy dữ liệu (qua Route chính thì trả về mã `UzpfSTYx...`, qua luồng phân trang cuộn trang IFS thì trả về mã con trỏ đệm tạm thời `UzpfSUZTOjE6...`).
- Do bảng `facebook.posts` đặt Khóa chính (Primary Key) trên cột `post_id`, khi nhận được 2 chuỗi ID khác nhau, PostgreSQL coi đó là 2 bài viết độc lập và chèn 2 hàng riêng biệt vào database, khiến giao diện hiển thị lặp lại cùng một bài viết 2 lần.
- **Giải pháp chuẩn hóa**: Bằng cách giải mã và quy về ID gốc `1432819905416474`, câu lệnh `ON CONFLICT (post_id)` của PostgreSQL lập tức nhận diện được bài viết đã tồn tại và thực hiện lệnh `UPDATE` cập nhật số like/comment thay vì chèn dòng mới.

---

## Mối liên hệ

- `extractor.py` $\rightarrow$ `repository.py` $\rightarrow$ `facebook.posts` table.
- Dashboard Frontend (`http://localhost:8888/facebook`): Bảng danh sách bài viết giờ đây hiển thị sạch sẽ, mỗi bài viết chỉ xuất hiện đúng 1 lần và tự động cập nhật số tương tác khi cào lại.

---

## Rủi ro & Lưu ý

- Không có rủi ro mất dữ liệu vì cơ chế chuẩn hóa ưu tiên giữ lại các chỉ số tương tác cao nhất (`GREATEST(reaction_count, EXCLUDED.reaction_count)`) và thời gian cập nhật mới nhất.
