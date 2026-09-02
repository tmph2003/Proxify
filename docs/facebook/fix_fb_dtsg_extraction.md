# Sửa lỗi trích xuất fb_dtsg từ Facebook

## Tóm tắt thay đổi
- Bổ sung nhiều biểu thức chính quy (regex patterns) vào file `auth_fetcher.py` để trích xuất linh hoạt token `fb_dtsg` và `lsd` từ HTML của Facebook.

## Mục đích & Ý nghĩa
- Facebook thường xuyên thay đổi cấu trúc giao diện HTML (A/B testing hoặc update phiên bản mới). Ban đầu hệ thống chỉ bóc tách token qua 1-2 pattern cố định nên khi Facebook đổi key (ví dụ đổi từ `DTSGInitialData` thành biến thể khác) sẽ gây lỗi "Không thể trích xuất fb_dtsg".
- Việc thêm nhiều Regex patterns dự phòng giúp quá trình lấy Authentication tokens (cần thiết để crawl dữ liệu) hoạt động ổn định và bền bỉ hơn bất chấp các thay đổi UI nhỏ từ Facebook.

## Mối liên hệ
- File `backend/proxify/platforms/facebook/auth_fetcher.py`: Nâng cấp bộ Regex Extractors cho `fb_dtsg` và `lsd`.
- Các tính năng Crawl (bài viết, bình luận) phụ thuộc trực tiếp vào token được cấp bởi file này.

## Rủi ro (Risks & Edge Cases)
- Mặc dù đã có nhiều Regex bao phủ phần lớn các trường hợp, Facebook vẫn có thể tung ra bản cập nhật lớn ẩn hoàn toàn Token vào các mã hóa mới. (Nếu điều này xảy ra, hệ thống sẽ cần đọc Token thẳng từ response API thay vì HTML parsing).
