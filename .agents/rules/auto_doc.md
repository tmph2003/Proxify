---
trigger: always_on
description: Tự động viết tài liệu (docs) sau khi có thay đổi trong source code.
---
# Auto Documentation Rule

BẤT CỨ KHI NÀO bạn (Agent) sử dụng các công cụ `replace_file_content` hoặc `write_to_file` để sửa/tạo code, bạn **BẮT BUỘC** phải thực hiện thêm một tác vụ nữa trước khi kết thúc lượt phản hồi:

1. **Phân tích** đoạn code vừa được viết/sửa đổi.
2. **Viết tài liệu:** Sử dụng tool `write_to_file` (hoặc `replace_file_content`) để tự động tạo/cập nhật một file tài liệu tương ứng trong thư mục `docs/` ở gốc dự án. 
   - Hãy tự động tổ chức cấu trúc thư mục `docs/` sao cho hợp lý, phản chiếu lại cấu trúc code (ví dụ: code ở `proxify/database/` thì doc lưu ở `docs/database/`).
3. **Nội dung bắt buộc:** File tài liệu BẮT BUỘC phải trình bày rõ ràng các mục sau bằng tiếng Việt:
   - **Tóm tắt thay đổi:** Giải thích ngắn gọn bạn vừa viết/sửa gì.
   - **Mục đích & Ý nghĩa:** Đoạn code này giải quyết vấn đề gì? Tại sao lại cần nó?
   - **Mối liên hệ:** Nó liên kết hoặc ảnh hưởng đến các module/file nào khác trong dự án?
   - **Rủi ro (Risks & Edge Cases):** Có rủi ro nào tiềm ẩn (bảo mật, hiệu năng, trường hợp ngoại lệ chưa xử lý triệt để) không?

**Lưu ý Nghiêm ngặt:** Tuyệt đối không được bỏ qua bước này. Mỗi khi sửa code xong, phải thấy lệnh gọi tool ghi vào thư mục `docs/`!
