# Tài liệu Giải quyết lỗi Numeric ID (Slug Resolution) cho Facebook Crawler

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/platforms/facebook/crawler.py` để bổ sung khả năng tự động phân giải (resolve) Facebook Group Slug (ví dụ `apikhongngonxoagroup`) thành Numeric ID (như `123456789`) trước khi đưa vào luồng crawler.
- Thêm hàm async `_resolve_numeric_group_id` dùng regex (`groupID":"(\d+)"` hoặc `group_id":"(\d+)"`) để bóc tách ID số học từ mã HTML.
- Chèn logic gọi hàm này vào đầu của `_execute_crawl_group_feed` để ghi đè (overwrite) biến `group_id` nếu người dùng truyền vào slug.

## Mục đích & Ý nghĩa
- **Khắc phục lỗi phá hoại Template GraphQL:** API GraphQL của Facebook có cơ chế Type Validation vô cùng nghiêm ngặt, bắt buộc `groupID` phải là Numeric ID. Nếu hệ thống sử dụng một chuỗi chữ (Slug) truyền vào Variables, GraphQL sẽ trả về lỗi HTTP 400 và làm hỏng toàn bộ luồng cào dữ liệu (Crawler). Thay đổi này đảm bảo API luôn nhận đúng Numeric ID dù user nhập URL dạng nào.

## Mối liên hệ
- File bị ảnh hưởng trực tiếp: `proxify/platforms/facebook/crawler.py`.
- Tác động tích cực đến API `/api/facebook/crawl` trong `proxify/plugins/facebook.py` khi user submit URL.

## Rủi ro (Risks & Edge Cases)
- **Regex Failures:** Facebook có thể thay đổi cấu trúc HTML trong tương lai, khiến đoạn regex `groupID":"(\d+)"` không còn hoạt động. Khi đó hàm `_resolve_numeric_group_id` sẽ fallback về việc trả lại đúng slug ban đầu (gây lỗi GraphQL như cũ). Cần theo dõi logs để phát hiện nếu tính năng này ngưng hoạt động.
- **Rate Limit (Block):** Hàm phân giải có thực hiện 1 request HTTP GET tới trang HTML của Facebook. Nếu user submit số lượng URL slug quá nhanh, request HTML này có nguy cơ bị Facebook chặn (soft-block), tuy nhiên rủi ro thấp do chỉ chạy 1 lần lúc bắt đầu crawl.
