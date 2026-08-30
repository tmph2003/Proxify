# Tài liệu: `proxify/plugins/facebook.py`

## 1. Tóm tắt tổng quan
File `facebook.py` là một plugin lớn và phức tạp, chuyên đánh chặn, lấy token, quản lý tác vụ quét (crawl) bình luận và bài đăng từ Facebook GraphQL. Nó cung cấp đầy đủ backend phục vụ cho Dashboard phân tích Facebook.

## 2. Mục đích & Ý nghĩa
- Tự động hóa quá trình nắm bắt (capture) cấu trúc (template) của Facebook GraphQL API.
- Cung cấp API để điều khiển tiến trình crawl tự động qua Playwright, cũng như crawl background bằng Python (bình luận, bulk actions).
- Kết nối người dùng (Dashboard UI) với Database để theo dõi, lọc, thống kê và cập nhật trạng thái bài viết/bình luận Facebook.

## 3. Mối liên hệ
- Kế thừa `BasePlugin` và đăng ký với tên `facebook`.
- Phụ thuộc rất lớn vào module `proxify.platforms.facebook`:
  - `crawler.py` để chạy luồng crawl bài/bình luận.
  - `database.py` (fb_db) để truy vấn/cập nhật CSDL.
  - `template_fetcher.py` (chạy qua subprocess) để tự mở Playwright lấy Cookie/Token mới.

## 4. Rủi ro (Risks & Edge Cases)
- **Lỗi Subprocess:** Hàm gọi fetcher Playwright bọc trong subprocess có thể treo hoặc không thoát sạch nếu bị kẹt, có rủi ro zombie process.
- **Bảo mật Cookie:** Cookie được lưu vào một biến memory global (`IN_MEMORY_COOKIES`). Cần đảm bảo môi trường bảo mật không để rò rỉ bộ nhớ.
- **Chặn (Block/Checkpoints):** Crawl Facebook với tốc độ nhanh hoặc liên tục kiểm tra trạng thái (`_bg_check_status`) có thể khiến tài khoản bị khóa checkpoint hoặc ban cookie.

## 5. Chi tiết các Class và Hàm
### Các biến cấp độ module
- `background_tasks`: Tập hợp (set) lưu trữ tham chiếu (strong reference) đến các asyncio tasks đang chạy nền, chống bị gom rác (garbage collection).
- `IN_MEMORY_COOKIES`: Dictionary lưu trữ tạm thời cookie Facebook do người dùng cấp phát.

### Class `FacebookPlugin(BasePlugin)`
- **Hàm `__init__`**: Khởi tạo plugin.
- **Hàm `on_request(self, flow: Any) -> None`**:
  - Đánh chặn request trỏ tới `facebook.com` chứa endpoint `/api/graphql`.
  - Phân tích `variables`, `friendly_name` (tên truy vấn FB).
  - Dùng để làm mẫu template: Lưu các query lấy "GroupsCometFeed" hoặc "comment" / "reply" vào `tokens.json`. Template này được hệ thống Crawler dùng lại để gọi API sau này.
- **Hàm `on_response(self, flow: Any) -> None`**:
  - Theo dõi người dùng nếu họ duyệt web tới 1 đường dẫn bài viết `permalink_url`.
  - Tự động nhận diện nội dung thông báo lỗi (VD: "Bạn hiện không xem được..."), qua đó tự động update trạng thái bài viết thành không khả dụng (inactive) trong Database.
- **Hàm `get_ui_tabs(self)` và `get_api_routes(self)`**:
  - Cung cấp URL Dashboard API và UI cho module Facebook.
- **Các hàm API Handler (bắt đầu bằng `_handle_...`)**:
  - `_handle_facebook_page`: Serve HTML giao diện.
  - `_handle_facebook_crawl`: Gọi subprocess thực thi Playwright chạy `fetch_fresh_template`, sau đó lấy template và gọi `start_crawler()` để crawl các bài viết nhóm. Hàm tự hủy cookie khỏi memory sau khi kết thúc.
  - `_handle_crawl_posts`: API nhận list URLs để crawler vào cào chi tiết bài viết (background task).
  - `_handle_crawl_status`: Trả về tiến độ và trạng thái group crawler.
  - `_handle_facebook_results`: Truy vấn bài đăng từ database (phân trang, lọc trạng thái, sắp xếp).
  - `_handle_save_cookie` & `_handle_get_cookie`: API thao tác lưu/xem cookie vào RAM. Cookie được mask 1 phần để bảo mật.
  - `_handle_get_comments`: Query lấy danh sách comment của 1 post cụ thể trong DB.
  - `_handle_crawl_comments`: Ra lệnh cào tất cả bình luận cho 1 post (sử dụng background task).
  - `_handle_comment_status`: Trả về trạng thái tiến trình cào bình luận.
  - `_handle_post_status`: Cập nhật trạng thái `is_active` cho nhiều bài viết cùng lúc.
  - `_handle_bulk_action`: API gánh vác nhiều hành động hàng loạt (switch/case) như:
    - `crawl_comments`: Crawl bình luận hàng loạt bài viết.
    - `check_status`: Sử dụng request thông thường (chống chặn bằng `StealthSessionManager`) truy cập URL kiểm tra bài viết còn sống hay không.
    - `refresh`: Cào/cập nhật lại dữ liệu các bài đăng.
    - `export_csv`: Xuất dữ liệu Database ra file CSV.
    - `delete`: Xoá sạch bài viết (và comment) khỏi DB.
  - `_handle_bulk_status`: Kiểm tra trạng thái tiến trình của tác vụ hàng loạt.
