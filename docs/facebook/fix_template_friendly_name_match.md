# Tóm tắt thay đổi

1. Sửa đổi logic lưu trữ `feed_template` trong `proxify/platforms/facebook/api.py`. Chuyển từ điều kiện so sánh bằng `friendly_name == "GroupsCometFeed"` sang sử dụng từ khóa `in` (kiểm tra chuỗi con).

# Mục đích & Ý nghĩa

- Chrome Extension (`background.js`) chặn các yêu cầu GraphQL từ Facebook và gửi payload có `friendly_name` đầy đủ là `GroupsCometFeedRegularStoriesPaginationQuery`.
- Do code cũ của Backend yêu cầu chuỗi khớp chính xác `== "GroupsCometFeed"`, nó đã liên tục từ chối (bỏ qua) payload thực tế này và không lưu vào bộ nhớ đệm `IN_MEMORY_TEMPLATES["feed"]`. 
- Hệ quả là Crawler (khi không tìm thấy template thực) đã tiếp tục sử dụng template "giả lập" cũ có `doc_id` đã chết (`8856247924484083`) bị kẹt lại trong RAM từ các lần chạy trước, gây ra lỗi "The GraphQL document... was not found".
- Việc sửa thành chuỗi con `in` đảm bảo Backend luôn đón nhận và lưu trữ đúng template mới nhất vừa được Extension gửi lên.

# Mối liên hệ

- Code backend trong `api.py` phụ thuộc trực tiếp vào cách `background.js` đóng gói và gửi `friendly_name` về cho hệ thống.

# Rủi ro (Risks & Edge Cases)

- Cần chú ý trong tương lai nếu Facebook đổi hẳn tên `GroupsCometFeed` thành một cái tên hoàn toàn mới, ta sẽ cần thêm tên mới vào khối điều kiện `if` này. Tuy nhiên hiện tại chuỗi con đã đủ bao quát.
