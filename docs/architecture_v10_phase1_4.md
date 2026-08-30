# Auto Documentation: Background Worker (CQRS Normalizer)

## 1. Tóm tắt thay đổi
- Khởi tạo `BackgroundWorker` (`proxify/core/worker.py`).
- Tích hợp vòng lặp tự động (chạy 2 giây/lần) để quét bảng `core.raw_payloads` và xử lý các sự kiện thô mà Proxy thu được.
- Đã xử lý 2 sự kiện cốt lõi của Facebook:
  - `facebook.graphql.request`: Cập nhật file `tokens.json`.
  - `facebook.post.status`: Đánh dấu bài viết bị vô hiệu hóa (inactive).
- Tích hợp khởi động `BackgroundWorker` vào `server_v2.py`.

## 2. Mục đích & Ý nghĩa
- Hoàn thiện luồng CQRS (Command Query Responsibility Segregation). Proxy chỉ làm nhiệm vụ ghi tốc độ cao (Command), trong khi Worker sẽ âm thầm chuẩn hóa dữ liệu (Query) ở Background mà không làm chậm mạng.
- Loại bỏ được sự phụ thuộc vào truy vấn đồng bộ của `FacebookPlugin` cũ khi đang lướt web.

## 3. Rủi ro (Risks & Edge Cases)
- Hiện tại worker vẫn đánh dấu `processed = TRUE` kể cả khi có lỗi xảy ra trong hàm xử lý, để tránh lỗi Poison Pill (cứ load lại 1 event lỗi mãi mãi). Ở môi trường production thực tế, chúng ta nên thêm trường `error_log` hoặc một bảng `dead_letter_queue` để tiện theo dõi.
- Do hàm cập nhật trạng thái bài viết sử dụng truy vấn `LIKE` với `permalink_url`, nếu bảng `facebook.posts` có hàng triệu bản ghi mà chưa đánh Index cho cột này, tốc độ cập nhật sẽ bị chậm lại. (Cần đánh index B-Tree hoặc pg_trgm sau này).
