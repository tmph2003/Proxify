

## 📝 Cập nhật (29/08/2026)

### Tóm tắt thay đổi
Sửa logic trích xuất eedback_id của Post trong extractor.py.

### Mục đích & Ý nghĩa
Facebook GraphQL thường xuyên giấu eedback_id sâu bên trong comet_sections thay vì để ở node gốc. Việc thiếu ID này khiến tính năng Lấy Bình Luận báo lỗi. Đoạn code mới dùng DataHelper.find_key(node, 'feedback') để quét đệ quy (recursive) tìm ra bằng được ID này.

### Rủi ro (Risks & Edge Cases)
Việc quét sâu có thể vô tình lấy nhầm eedback_id của một comment bên trong bài viết thay vì của chính bài viết, nên chúng ta chỉ lấy node đầu tiên thoả mãn.
