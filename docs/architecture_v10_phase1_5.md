# Auto Documentation: Tách rời API Dashboard (OCP Compliance)

## 1. Tóm tắt thay đổi
- Chuyển dời toàn bộ logic API của Dashboard từ plugin cũ sang file `proxify/platforms/facebook/api.py`.
- Tách lớp `FacebookAPI` mới, xóa bỏ sự kế thừa từ `BasePlugin`.
- Tích hợp `FacebookAPI` trực tiếp vào `FacebookPlatform` (IPlatformHandler) để `server_v2.py` có thể mount các router này một cách độc lập.

## 2. Mục đích & Ý nghĩa
- Tôn trọng triết lý Single Responsibility Principle (SRP) và Open-Closed Principle (OCP). Thay vì một cục monolith `facebook.py` ôm cả proxy hook, crawler logic, DB query và HTTP API, nay chúng được chia tách rõ ràng:
  - `interceptor.py`: Bắt gói tin (Proxy hook).
  - `api.py`: Phục vụ giao diện Dashboard.
  - `crawler.py`: Chạy background scrape dữ liệu.
- Hoàn toàn làm sạch thư mục `plugins/` cũ, dọn đường cho việc vứt bỏ phiên bản v1.

## 3. Rủi ro (Risks & Edge Cases)
- Các endpoint trong `api.py` vẫn đang dùng `psycopg2` đồng bộ (`fb_db.pool.cursor`). Mặc dù aiohttp xử lý IO multiplexing, nhưng nếu có truy vấn siêu nặng, nó có thể gây block (khựng) nhẹ event loop của Dashboard. Ở Giai đoạn 2 (Database Migration), ta sẽ cấu hình lại toàn bộ các route này sang dùng `DatabaseManager` (`asyncpg`).
