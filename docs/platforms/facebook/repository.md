# Tài liệu: `proxify/platforms/facebook/repository.py`

## 1. Tóm tắt tổng quan
File `repository.py` triển khai mẫu thiết kế Repository Pattern để đảm nhiệm vai trò truy vấn và thao tác trên từng bảng riêng biệt của PostgreSQL (nằm trong schema `facebook`). Nó tách biệt logic lưu trữ khỏi logic xử lý nghiệp vụ, bao gồm 4 Repository: Author, Post, Comment, Config.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Cung cấp các thao tác CRUD (chủ yếu là Upsert: Insert or Update) cho các thực thể cụ thể. 
- **Ý nghĩa**: Tái sử dụng các câu lệnh SQL dài dòng, giảm thiểu nguy cơ sai sót. Bằng cách hỗ trợ truyền `cursor` vào từ bên ngoài, nó cho phép nhiều thao tác lưu dữ liệu được thực thi trong chung một giao dịch (transaction) để đảm bảo tính nhất quán của dữ liệu (ACID).

## 3. Mối liên hệ
- File này được import và khởi tạo từ file `database.py`.
- Lớp `DocumentLinker` trong `extractor.py` gọi các repository này để Upsert Authors, Posts, và Comments sau khi bóc tách xong từ JSON trả về của GraphQL.

## 4. Rủi ro (Risks & Edge Cases)
- **Tắc nghẽn DB (Deadlocks)**: Việc dùng `ON CONFLICT DO UPDATE` với tần suất cực cao trên cùng một khoá (ví dụ update comment_count của cùng một bài viết liên tục) có thể gây khóa hàng (Row-level lock) và làm chậm truy vấn.
- **Sai kiểu dữ liệu (Data Type Error)**: Các trường `creation_time` nhận vào dạng int, nhưng nếu bóc tách lỗi ra chuỗi hoặc rỗng, hàm `fromtimestamp` có thể bị lỗi. Rất may đã có `try...except` để pass lỗi này.
- **Ghi đè sai lệch dữ liệu cũ**: ON CONFLICT của PostRepository sử dụng `GREATEST` để lấy giá trị like/comment cao hơn, tránh việc ghi đè số liệu mới thấp hơn số cũ (do crawler bị trễ/lỗi). Tuy nhiên, nếu một bài viết thực sự bị mất bình luận (xoá), DB sẽ không bao giờ giảm số xuống.

## 5. Chi tiết các Class và Hàm

### 1. `AuthorRepository` (Class)
- **Mô tả**: Lưu trữ thông tin người dùng / tác giả.
- **Các hàm**:
  - `__init__(self, pool)`: Nhận đối tượng pool kết nối.
  - `upsert(self, author: dict, cursor=None) -> None`: Chèn hoặc cập nhật một tác giả vào bảng `authors`. Sử dụng hàm nội bộ `_do_upsert`.
  - `_do_upsert(self, cur, author: dict)`: Chạy câu truy vấn `INSERT ... ON CONFLICT DO UPDATE` thông qua cursor, cập nhật `last_seen` và lấy giá trị có thực nếu bản ghi mới rỗng.

### 2. `PostRepository` (Class)
- **Mô tả**: Lưu trữ thông tin bài viết.
- **Các hàm**:
  - `__init__(self, pool)`: Nhận đối tượng pool.
  - `upsert(self, post: dict, cursor=None) -> None`: Chèn/Cập nhật bài viết vào bảng `posts`.
  - `_do_upsert(self, cur, post: dict)`: Định dạng ngày tháng, chuyển danh sách ảnh/video thành JSON chuỗi. Gọi `INSERT ... ON CONFLICT DO UPDATE`. Chỉ cập nhật khi nội dung chữ, lượt like, comment, share, trạng thái is_active hoặc feedback_id bị thay đổi (để tránh update vô ích).

### 3. `CommentRepository` (Class)
- **Mô tả**: Lưu trữ bình luận, bao gồm cả Reply (thông qua `parent_comment_id`).
- **Các hàm**:
  - `__init__(self, pool)`: Nhận đối tượng pool.
  - `upsert(self, comment: dict, post_id: str, cursor=None) -> None`: Upsert bình luận vào `comments`.
  - `_do_upsert(self, cur, comment: dict, post_id: str)`: Lưu bình luận, gắn với `post_id`. Cũng sử dụng `GREATEST` để lưu lượt phản hồi (reply) lớn nhất.

### 4. `ConfigRepository` (Class)
- **Mô tả**: Bảng lưu trữ Key-Value (chuỗi) để giữ các thiết lập, trạng thái cấu hình của nền tảng (ví dụ: con trỏ pagination cũ).
- **Các hàm**:
  - `__init__(self, pool)`: Nhận đối tượng pool.
  - `set(self, key: str, value: str) -> None`: Upsert một key-value vào bảng `config`.
  - `get(self, key: str) -> Optional[str]`: Lấy value theo key, trả về None nếu không tồn tại.
