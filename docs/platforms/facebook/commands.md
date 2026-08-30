# Tài liệu: `proxify/platforms/facebook/commands.py`

## 1. Tóm tắt tổng quan
File `commands.py` triển khai mẫu thiết kế Command (Command Pattern) để đóng gói các yêu cầu thực thi chức năng liên quan đến việc thu thập dữ liệu Facebook (crawler). Nó định nghĩa một class cơ sở (BaseCommand) và các class con cụ thể để thực hiện các nhiệm vụ như refresh bài viết, lấy dữ liệu bảng tin (feed) của nhóm, và lấy bình luận (comments).

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Đóng gói mọi thông tin cần thiết (receiver, tham số url, cookie, etc.) của một yêu cầu (request) vào một object (command). 
- **Ý nghĩa**: Điều này cho phép hàng đợi (queue) hoặc worker trong `FacebookCrawler` có thể nhận, xử lý tuần tự, và quản lý các yêu cầu thu thập một cách dễ dàng, bảo đảm tính an toàn đa luồng (thread-safe/mutex) để tránh bị khóa (block) do gửi quá nhiều request đồng thời lên Facebook.

## 3. Mối liên hệ
- Các command được khởi tạo và đẩy vào queue bên trong `FacebookCrawler` (trong `crawler.py`).
- Receiver được truyền vào mỗi command chính là instance của `FacebookCrawler`. Khi command gọi `execute()`, nó sẽ gọi ngược lại các phương thức nội bộ (như `_execute_crawl_group_feed`) của `FacebookCrawler`.

## 4. Rủi ro (Risks & Edge Cases)
- **Tắc nghẽn Queue (Queue Bottleneck)**: Vì mọi tác vụ phải chạy qua cơ chế Command và Queue tuần tự, nếu một command bị kẹt hoặc mất quá nhiều thời gian, toàn bộ hệ thống crawl sẽ bị treo.
- **Memory Leak**: Nếu các command lưu giữ quá nhiều dữ liệu lớn (như nguyên template HTML) mà không được garbage collector giải phóng sau khi chạy, có thể gây tràn RAM.
- **Rủi ro vòng lặp (Circular Dependency)**: Command phải chứa tham chiếu đến Crawler (receiver) và Crawler phải import Command. Phải cẩn trọng về cấu trúc import để không gây lỗi.

## 5. Chi tiết các Class và Hàm

### 1. `BaseCommand` (Class)
- **Mô tả**: Lớp trừu tượng (Abstract Base Class) đại diện cho mẫu Command.
- **Các hàm**:
  - `async def execute(self)`: (Abstract) Phương thức trừu tượng, bắt buộc các lớp kế thừa phải triển khai nội dung thực thi tác vụ.

### 2. `RefreshCommand(BaseCommand)` (Class)
- **Mô tả**: Command dùng để yêu cầu làm mới (refresh) thông tin (lượt thích, bình luận) của các bài viết cụ thể trên Facebook.
- **Các hàm**:
  - `__init__(self, receiver, urls: list[str], template: dict = None, client_cookie: str = None)`: Hàm khởi tạo, lưu lại instance của crawler (`receiver`), danh sách URLs cần refresh, template xác thực và cookie của người dùng.
  - `async def execute(self)`: Gọi hàm `_execute_crawl_specific_posts` của `receiver` (crawler) và truyền các tham số đã lưu vào. Ghi log trước khi bắt đầu chạy.

### 3. `CrawlFeedCommand(BaseCommand)` (Class)
- **Mô tả**: Command dùng để yêu cầu cào dữ liệu toàn bộ bài viết trên bảng tin (feed) của một Group Facebook.
- **Các hàm**:
  - `__init__(self, receiver, group_id: str, start_ts: int, end_ts: int, template: dict = None, client_cookie: str = None)`: Hàm khởi tạo, lưu lại `receiver`, ID nhóm (`group_id`), khoảng thời gian (`start_ts`, `end_ts`), template và cookie.
  - `async def execute(self)`: Thực thi bằng cách gọi `_execute_crawl_group_feed` trên `receiver` (crawler) với các tham số tương ứng. Ghi log thao tác.

### 4. `CrawlCommentCommand(BaseCommand)` (Class)
- **Mô tả**: Command dùng để cào toàn bộ bình luận và phản hồi (replies) của một bài viết cụ thể.
- **Các hàm**:
  - `__init__(self, receiver, post_id: str, feedback_id: str, template: dict = None, client_cookie: str = None)`: Hàm khởi tạo, lưu `receiver`, ID bài viết (`post_id`), ID phản hồi của bài viết trong GraphQL (`feedback_id`), template và cookie.
  - `async def execute(self)`: Chạy hàm `_execute_crawl_comments` trên `receiver` (crawler) để bắt đầu lấy comments. Ghi log thao tác.
