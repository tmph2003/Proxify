# Tài liệu Sửa lỗi Phân giải Slug Facebook Crawler (Bug Fix)

## Tóm tắt thay đổi
- Sửa hàm `_resolve_numeric_group_id` trong file `proxify/platforms/facebook/crawler.py`.
- **Cập nhật phương thức HTTP**: Thay thế hàm `.get()` (gây lỗi `AttributeError` do không tồn tại) bằng `.request("GET", ...)` tương thích với `StealthSessionManager`.
- **Nâng cấp Regex**: Nâng cấp biểu thức chính quy từ `(?:"groupID":"|"group_id":")(\d+)"` lên `(?:groupID|group_id)["\'\\]*\s*:\s*["\'\\]*(\d+)` để quét được toàn bộ các trường hợp ID bị nhúng, bị escape (`\"`), hoặc dạng integer không có nháy.
- **Xử lý Exception an toàn hơn**: Loại bỏ Anti-pattern `except Exception: pass`, thay thế bằng `logger.warning(...)` để xuất log lỗi rõ ràng nhằm phục vụ debug tương lai nếu regex hỏng hoặc rớt mạng.

## Mục đích & Ý nghĩa
- **Khôi phục khả năng quét dữ liệu:** Lỗi `.get()` bị nuốt (silent failure) trước đây khiến hệ thống truyền thẳng Slug vào Facebook GraphQL, dẫn đến lỗi 400 Bad Request làm Crawler không lấy được Post. Sau khi sửa, hệ thống khôi phục hoàn toàn tính năng Crawl qua URL Slug.
- **Tính ổn định cao (Robustness):** Đảm bảo Crawler sẽ không bị đánh lừa bởi các định dạng JSON/HTML dị biệt (thừa khoảng trắng, bị parse chuỗi escape) mà Facebook thường xuyên cập nhật.

## Mối liên hệ
- Liên quan mật thiết tới module `proxify/platforms/facebook/crawler.py` (cơ chế phân giải ID).
- Tương tác với class `StealthSessionManager` (trong `stealth.py`).

## Rủi ro (Risks & Edge Cases)
- **Lỗi bất khả kháng:** Trường hợp Facebook chuyển sang giấu kín Numeric ID trong các request tách biệt mà không render ra HTML ban đầu, hàm regex này sẽ trả về giá trị cũ (Slug). Nhờ có cơ chế logging mới thêm vào, Developer sẽ nhận biết được ngay lập tức thông qua terminal/log file.
