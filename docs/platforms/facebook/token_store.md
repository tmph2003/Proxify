# Tài liệu: `proxify/platforms/facebook/token_store.py`

## 1. Tóm tắt tổng quan
File `token_store.py` chịu trách nhiệm độc lập trong việc tìm kiếm, tải, xử lý và phân tách các thông tin định danh/xác thực (như tokens, cookies, User-Agent, template request) của nền tảng Facebook. Nó là một module Single Responsibility (Chỉ đảm nhận một trách nhiệm duy nhất).

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Đóng gói hoàn toàn quy trình xử lý Token và Cookie. Tránh việc rải rác các đoạn code đọc/ghi cookie khắp các module crawler hay extractor.
- **Ý nghĩa**: Bất kỳ hệ thống cào dữ liệu (crawler) nào cũng cần 1 cookie sống và hợp lệ. Tập trung quản lý truy xuất vào một nơi giúp cho việc thay thế cookie hoặc thay đổi định dạng lưu trữ (từ file sang database) trở nên vô hình đối với Crawler.

## 3. Mối liên hệ
- File này được import và sử dụng trong hàm `_execute_crawl_group_feed`, `_execute_crawl_specific_posts`, `_execute_crawl_comments` của `FacebookCrawler` (file `crawler.py`) để lấy cookies và template trước khi chạy vòng lặp cào dữ liệu.

## 4. Rủi ro (Risks & Edge Cases)
- **Tập tin bị ghi đè không tương thích**: Phương thức `get_saved_tokens` cố gắng tìm file `tokens_facebook.json` trong `data/` rồi mới tới `tokens.json`. Nếu định dạng json bị sai cấu trúc hoặc file bị mã hóa nhầm, module sẽ trả về `None`, làm gián đoạn mọi tiến trình Crawler.
- **Xử lý Cookie sai**: Hàm `parse_cookie_string` dựa vào dấu phẩy `,` hoặc chấm phẩy `;` để cắt chuỗi. Đôi khi nội dung của cookie có chứa ký tự này ở định dạng chuẩn làm mã phân tách sai (mặc dù FB ít bị lỗi này nhưng đây là rủi ro chung của việc parse cookie bằng chuỗi).

## 5. Chi tiết các Class và Hàm

### 1. Hàm `async def get_saved_tokens() -> Optional[dict]`
- **Mô tả**: Tải tệp tin token của Facebook.
- **Cách hoạt động**: Ưu tiên tìm tại `<project>/data/tokens_facebook.json` (thường dùng trong Docker), nếu không có sẽ tìm `<package>/platforms/facebook/tokens.json`. Cố gắng parse JSON và trả về kết quả, nếu lỗi trả về `None`.

### 2. Hàm `async def get_cookies_and_ua_from_db(pool) -> tuple[dict, str]`
- **Mô tả**: Tìm cookie Facebook và chuỗi User-Agent mới nhất từ Database chứa lịch sử mạng.
- **Cách hoạt động**: Dùng lệnh SQL truy vấn vào bảng `public.requests`, tìm request mới nhất (`ORDER BY timestamp_epoch DESC LIMIT 1`) trỏ về `facebook.com` mà có header chứa `cookie`. Lấy cookie và user-agent, sau đó dùng `parse_cookie_string` chuyển cookie thành dạng dict và trả về cùng chuỗi User-Agent.

### 3. Hàm `def parse_cookie_string(cookie_str: str) -> dict[str, str]`
- **Mô tả**: Phân tách chuỗi cookie thô (thường lấy từ header HTTP) thành từ điển Key-Value.
- **Cách hoạt động**: Tách theo dấu `,` hoặc `;`, chạy vòng lặp, cắt theo dấu `=` ở vị trí đầu tiên. Cắt khoảng trắng dư thừa hai đầu.

### 4. Hàm `def extract_templates(tokens: dict) -> tuple[Optional[dict], Optional[dict], Optional[dict]]`
- **Mô tả**: Tách các mẫu tin request (templates) được lưu trong biến tokens.
- **Cách hoạt động**: Xử lý khả năng tương thích ngược. Nếu cấu trúc `tokens` là dạng lưới chứa các khóa `feed`, `comment`, `reply` thì nó sẽ phân rã thành một tuple tương ứng. Nếu cấu trúc phẳng (chỉ chứa `form_data` trực tiếp), nó hiểu đây là dạng legacy (cũ) và sẽ trả template đó như là feed (feed_template), còn lại là `None`. Trả về `(feed_template, comment_template, reply_template)`.
