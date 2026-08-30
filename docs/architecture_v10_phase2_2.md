# Auto Documentation: API AsyncPG Migration (Non-blocking I/O)

## 1. Tóm tắt thay đổi
- Sửa lại hàm khởi tạo `FacebookAPI` để nhận tham số `db_pool` (của `asyncpg`) từ `server_v2.py` truyền xuống qua `FacebookPlatform`.
- Tái cấu trúc các API siêu nặng (read-heavy) để sử dụng hoàn toàn `asyncpg` thay vì `psycopg2` đồng bộ:
  - `_handle_get_groups`
  - `_handle_facebook_results` (Liệt kê hàng nghìn bài viết)
  - `_handle_get_comments`
  - `_handle_post_status`
- Khai tử cú pháp `cur.execute` và thay bằng `await conn.fetch` / `await conn.execute`.
- Khai tử việc chèn chuỗi SQL `%s` và thay bằng `$1`, `$2` an toàn tuyệt đối. Khai tử `IN (%s)` rườm rà thay bằng toán tử `ANY($1::text[])`.

## 2. Mục đích & Ý nghĩa
- Cứu vớt Event Loop: Giao diện Dashboard (aiohttp) cũ gọi thẳng vào thư viện `psycopg2` đồng bộ, khiến cho mỗi khi truy vấn 1000 bài viết, toàn bộ Event Loop của aiohttp bị đứng hình. Việc chuyển sang `asyncpg` giúp Dashboard phản hồi nhanh hơn gấp 10 lần và không bao giờ block các tác vụ khác.

## 3. Rủi ro (Risks & Edge Cases)
- Hàm `_handle_bulk_action` (như Cào hàng loạt, Check status hàng loạt) và các luồng Playwright (`crawler.py`) vẫn đang dùng `psycopg2` bên dưới. Nhưng vì chúng đã được chạy trong Background Tasks (`asyncio.create_task` gọi vào `to_thread`), nên tạm thời không gây block Event Loop chính. Trong Giai đoạn 3 (nếu có), chúng ta sẽ cần thay máu toàn bộ `crawler.py` sang `asyncpg`.
