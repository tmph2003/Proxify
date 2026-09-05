# Tài liệu Khắc phục Lỗi Vòng đời Worker và Rò rỉ Tài nguyên Asyncio (Task Pending Leak)

## 1. Tóm tắt thay đổi
- **Tập tin sửa đổi:**
  - [`backend/proxify/platforms/facebook/crawler.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/platforms/facebook/crawler.py): Chuyển đổi cơ chế khởi tạo worker tasks `_feed_worker_task` và `_comment_worker_task` từ Eager (khởi tạo ngay trong `__init__`) sang **Lazy Initialization** (chỉ kích hoạt khi có lệnh thực tế được đưa vào queue qua `_ensure_feed_worker()` và `_ensure_comment_worker()`).
  - [`backend/proxify/platforms/facebook/api.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/platforms/facebook/api.py): Thay thế việc khởi tạo `crawler = FacebookCrawler(client_id=client_id)` dạng throwaway trong endpoint lưu cookie `/api/facebook/cookie` bằng việc gọi qua singleton `_default_crawler._synthesize_feed_template(...)`.

## 2. Mục đích & Ý nghĩa
- **Khắc phục lỗi Runtime nghiêm trọng trong Docker:**
  Trước đó, trong log Docker của `proxify_app` liên tục xuất hiện ngoại lệ:
  ```text
  ERROR:mitmproxy.master:Unhandled asyncio error: {'message': 'Task was destroyed but it is pending!', 'task': <Task pending name='Task-...' coro=<FacebookCrawler._feed_worker_loop() done> wait_for=<Future cancelled>>}
  ```
- **Nguyên nhân gốc rễ:** Mỗi khi Extension gửi cookie lên server, hàm `save_cookie` trong `api.py` tạo một instance `FacebookCrawler` mới. Constructor của Facade class này lập tức tạo 2 coroutine task chạy vòng lặp vô hạn `while True: await self._feed_queue.get()`. Khi request HTTP hoàn tất, biến `crawler` bị Garbage Collection (GC) của Python dọn dẹp, nhưng 2 task con vẫn đang treo trên event loop của mitmproxy, khiến asyncio báo lỗi `Task was destroyed but it is pending!`.
- **Giải pháp:**
  - Áp dụng nguyên tắc **Lazy Initialization**: Worker chỉ được sinh ra khi có công việc thực sự cần xử lý.
  - Tái sử dụng `_default_crawler` cho các tác vụ tiện ích tổng hợp template, triệt tiêu việc tạo rác đối tượng không kiểm soát.

## 3. Mối liên hệ
- **Tầng Domain (Facade):** `FacebookCrawler` quản lý hàng đợi và phân phối command (`CrawlFeedCommand`, `CrawlProfileFeedCommand`, `CrawlCommentCommand`, `RefreshCommand`).
- **Tầng Application (API Handler):** `api.py` xử lý các luồng HTTP từ Chrome Extension và Dashboard.
- **Môi trường Container (Docker):** Loại bỏ hoàn toàn các lỗi unhandled exception làm ô nhiễm log của `proxify_app` và event loop của mitmproxy.

## 4. Rủi ro (Risks & Edge Cases)
- **Đảm bảo tính liên tục của Task:** Nếu worker task trước đó bị kết thúc (done hoặc exception), hàm `_ensure_feed_worker()` và `_ensure_comment_worker()` sẽ tự động kiểm tra `task.done()` và tái kích hoạt một task mới một cách an toàn.
- **Multi-tenancy:** Các instance riêng lẻ (nếu được khởi tạo có chủ đích theo từng tenant) sẽ chỉ tiêu tốn tài nguyên khi có lệnh crawl thực sự, không gây rò rỉ bộ nhớ hoặc CPU cho hệ thống.
