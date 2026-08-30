# Tài liệu: Sửa lỗi hiển thị tiến độ (progress date) khi cào Facebook

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/platforms/facebook/crawler.py`: Thay thế hàm lấy ngày cũ nhất `min(timestamps)` bằng hàm lấy ngày trung vị `statistics.median(timestamps)` khi tính toán và hiển thị thông điệp tiến độ "Đã quét đến ngày...". 
- Thay đổi câu thông báo từ "Đã quét đến ngày X" thành "Đang quét bài viết quanh ngày X".

## Mục đích & Ý nghĩa
- Mặc định Facebook sắp xếp bài viết trong Group theo thuật toán "Hoạt động mới nhất" (Top Posts). Điều này dẫn đến việc một bài viết cực kỳ cũ (ví dụ cách đây vài tháng hoặc vài tuần) nếu vô tình có người comment thì sẽ bị đẩy (bump) lên ngay trang 1. 
- Ở code cũ, hệ thống lấy `min(timestamps)` (ngày cũ nhất trong các bài thu được ở trang hiện tại) để báo cáo. Do đó, chỉ cần 1 bài viết cũ bị đẩy lên trang 1, hệ thống sẽ báo ngay là "Đã quét đến ngày [cũ]" gây hiểu lầm nghiêm trọng cho người dùng về tiến độ quét thực tế.
- Việc sử dụng `median` (trung vị) sẽ bỏ qua các giá trị ngoại lai (outlier) này, phản ánh đúng 90% số lượng bài viết trong trang đó đang tập trung ở khoảng ngày nào.

## Mối liên hệ
- Chỉ ảnh hưởng đến UI State update được gửi qua WebSocket. Dữ liệu thực tế không bị ảnh hưởng.

## Rủi ro (Risks & Edge Cases)
- `statistics.median` có thể sinh lỗi nếu mảng truyền vào rỗng. Tuy nhiên logic code đã được bọc trong điều kiện `if timestamps:` nên đảm bảo an toàn.
