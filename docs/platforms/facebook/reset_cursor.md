# Tự động reset con trỏ (cursor) khi người dùng chủ động click Crawl

## Tóm tắt thay đổi
1. **`crawler.py`**:
   - Chỉnh sửa logic khởi tạo biến `cursor` của GraphQL trong hàm `_execute_crawl_group_feed`.
   - Thêm tham số `reset_cursor: bool = True` vào luồng gọi hàm từ ngoài vào trong: `start_crawler` -> `crawl_group_feed` -> `_execute_crawl_group_feed`.
   - Khi cào vòng lặp `MAX_PAGES_PER_SESSION`, nếu `reset_cursor=True`, hệ thống sẽ gọi `fb_db.config.set(...)` để ép trống cursor cũ trước khi lấy ra.
2. **`commands.py`**:
   - Thêm `reset_cursor: bool = True` vào class `CrawlFeedCommand` và luồng gọi `execute()`.

## Mục đích & Ý nghĩa
- Sửa lỗi UX (Trải nghiệm người dùng): Trước đây, tính năng tiếp tục (resume) được bật vĩnh viễn (lấy cursor cũ từ DB). Điều này dẫn đến việc người dùng muốn crawl lại các bài đăng *mới nhất* từ hôm nay lại bị bắt ép đi tiếp từ trang 90 của năm cũ.
- Giờ đây, khi gọi API từ UI, hệ thống sẽ reset cursor về rỗng để luôn cào bài đăng từ mới nhất trở xuống, giúp không bỏ lỡ dữ liệu cập nhật.

## Mối liên hệ
- Ảnh hưởng trực tiếp đến `api.py` khi nó kích hoạt tính năng lấy dữ liệu thông qua `start_crawler`.
- Nếu sau này hệ thống gặp lỗi crash ngầm cần tự phục hồi, ta có thể chủ động gọi `start_crawler(reset_cursor=False)` để nó lấy lại `cursor` dang dở từ Postgres.

## Rủi ro (Risks & Edge Cases)
- Do cơ chế Resume (nhớ vị trí) bị ngắt đối với các lệnh thủ công (manual request), nên nếu người dùng đang crawl 5000 trang mà bị lỗi 403, và họ ấn "Crawl" lại lần nữa từ UI, nó sẽ bắt đầu cào lại từ trang số 1 chứ không lướt tiếp trang 5001. Điều này là hợp lý để lấy dữ liệu mới, nhưng có thể lặp dữ liệu (DB có ON CONFLICT DO UPDATE rồi nên không lo).
