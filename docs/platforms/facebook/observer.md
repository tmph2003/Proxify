# Tài liệu: `proxify/platforms/facebook/observer.py`

## 1. Tóm tắt tổng quan
File `observer.py` xây dựng một kiến trúc quản lý trạng thái theo mẫu thiết kế Theo Dõi (Observer Pattern). Nó cung cấp một nơi lưu trữ trung tâm trạng thái quá trình crawl, trạng thái làm mới dữ liệu (refresh) và trạng thái lấy bình luận của hệ thống Facebook.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Tách biệt luồng chạy logic (crawler) với luồng hiển thị giao diện/tiến độ (UI/Progress). Các crawler chỉ việc "bắn" tín hiệu (update trạng thái) về một chỗ, giao diện hoặc webhook sẽ đọc từ chỗ đó.
- **Ý nghĩa**: Giúp giảm sự ràng buộc lỏng (decouple) mã nguồn. Crawler không cần biết dữ liệu được hiển thị thế nào, nó chỉ gọi các phương thức trong này để báo cáo tiến trình.

## 3. Mối liên hệ
- Các file `crawler.py` (chủ yếu là crawler Facade) gọi đối tượng `state_observer` để báo cáo tiến độ khi qua mỗi trang hoặc sau mỗi post.
- Giao diện người dùng Web (thường là FastAPI/WebSockets) sẽ đọc các thuộc tính của `state_observer` để trả về cho người dùng xem trạng thái (running, paused, blocked).

## 4. Rủi ro (Risks & Edge Cases)
- **Không thread-safe tuyệt đối**: Object này dùng `dict` thuần trong Python, mặc dù GIL (Global Interpreter Lock) đảm bảo an toàn cho nhiều thao tác đơn giản nhưng trong kiến trúc bất đồng bộ (asyncio) đôi lúc có thể gặp tình huống mất đồng bộ nếu đọc/ghi phức tạp đồng thời.
- **Memory Leak trong tiến trình Comment**: Thuộc tính `_comment_progress` là một dictionary lưu theo `post_id`. Nếu crawl hàng vạn bài viết, dict này sẽ phình to mãi mãi do không có cơ chế dọn dẹp (cleanup/delete) các tiến trình cũ đã hoàn tất.

## 5. Chi tiết các Class và Hàm

### 1. `CrawlerStateObserver` (Class)
- **Mô tả**: Quản lý và lưu trữ trạng thái của các tiến trình cào dữ liệu (feed, refresh, comments).
- **Thuộc tính**:
  - `crawl_state`: (dict) Trạng thái của feed crawler. Có các key `status`, `group_id`, `message`.
  - `refresh_progress`: (dict) Tiến độ làm mới nhiều URL cùng lúc. Có các key `total`, `current`, `status`.
  - `_comment_progress`: (dict) Trạng thái cào comment cho từng bài viết cụ thể, được đánh chỉ mục bằng `post_id`.

- **Các hàm**:
  - `__init__(self)`: Khởi tạo các dictionary lưu trạng thái rỗng hoặc idle.
  - `update_crawl_state(self, status: str = None, message: str = None, group_id: str = None)`: Cập nhật giá trị vào `crawl_state`.
  - `reset_refresh_progress(self, total: int)`: Thiết lập lại thông số để bắt đầu tiến trình Refresh (total).
  - `increment_refresh_progress(self)`: Tăng `current` lên 1. Nếu `current` bằng `total`, đổi `status` thành `idle`.
  - `set_refresh_status(self, status: str)`: Cập nhật trạng thái cho quá trình Refresh.
  - `update_comment_progress(self, post_id: str, status: str, message: str, count: int = 0)`: Tạo hoặc cập nhật tiến trình cào comment cho một `post_id`. Nó cộng gộp số comment đã lấy được vào `total`.
  - `get_comment_progress(self, post_id: str)`: Lấy thông tin trạng thái của một tiến trình cào comment theo `post_id`.

### Biến toàn cục: `state_observer`
- Thực thể (Instance) duy nhất (Singleton) của `CrawlerStateObserver`, cung cấp điểm truy xuất trạng thái toàn cục cho mọi module khác.
