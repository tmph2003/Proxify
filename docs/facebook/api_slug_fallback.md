# Hỗ trợ trích xuất Slug Group khi Group ID bị thiếu

## 1. Tóm tắt thay đổi
Đã cập nhật câu truy vấn SQL trong hàm `_handle_get_groups` thuộc file `proxify/platforms/facebook/api.py` để tự động trích xuất slug của group từ đường dẫn bài viết (`permalink_url`) trong trường hợp các bài viết được cào về không có thông tin `group_id`.

## 2. Mục đích & Ý nghĩa
- **Vấn đề trước đây:** Với một số group đặc thù (hoặc do crawler chưa tối ưu cho mọi định dạng URL), trường `group_id` trong database có thể bị bỏ trống (nhận giá trị `NULL`). Khi đó, API `/api/facebook/groups` trả về danh sách nhóm với ID là `null`, khiến UI không thể đồng bộ ID/slug sang ô **Group ID** để người dùng thao tác cào tiếp.
- **Giải pháp:** Sử dụng hàm `COALESCE` kết hợp với Regular Expression trong PostgreSQL (`substring(permalink_url from '/groups/([^/]+)/')`) để bóc tách slug từ `permalink_url` (ví dụ: `apikhongngonxoagroup`) khi `group_id` bị thiếu. Nhờ đó, backend sẽ trả về slug như một ID hợp lệ. Frontend UI vốn dĩ đã có sẵn logic trích xuất slug, nên giờ đây slug sẽ được tự động điền vào ô "Cào dữ liệu" một cách mượt mà.

## 3. Mối liên hệ
- File chỉnh sửa: `proxify/platforms/facebook/api.py`.
- Tương tác với tính năng hiển thị Dropdown lọc theo Group trên giao diện và module Crawler (vì crawler đã được thiết kế để nhận diện và bắt theo slug nếu không có chuỗi số ID).

## 4. Rủi ro (Risks & Edge Cases)
- Regex `/groups/([^/]+)/` chỉ bắt chuẩn xác đối với các bài viết có định dạng URL thông thường chứa tiền tố `/groups/`. Đối với các group hoặc trang có định dạng URL khác lạ hơn (rất hiếm gặp ở Facebook Group), biểu thức này có thể trả về giá trị không như mong đợi. Tuy nhiên, rủi ro này thấp vì đa số các bài viết được nạp vào DB đều tuân theo chuẩn permalink của FB.
- Cần **khởi động lại hệ thống server (backend)** để các code Python có hiệu lực, hoặc đợi 5 phút cho bộ nhớ cache của danh sách Group tự động xóa thì tính năng này mới hiển thị ra API.
