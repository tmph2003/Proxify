# Tài liệu: Cập nhật điều kiện chặn Ads YouTube và sửa logic Plugin

## Tóm tắt thay đổi
- Sửa lại file `proxify/utils/youtube_utils.py`: Chỉnh lại phần thụt lề (indentation) của các lệnh `if` kiểm tra tên miền `doubleclick.net` và URL chứa `api/stats/ads` hoặc `ad_`. 
- Sửa file `proxify/server_v2.py`: Chuyển cờ đăng ký `YouTubePlugin` vào `ProxyRouter` từ `False` (Observer - chạy nền không thể block request) thành `True` (Mutator - chạy đồng bộ để có thể gọi `flow.kill()` chặn request).
- Sửa file `proxify/plugins/base.py`: Bổ sung 2 phương thức `handle_request` và `handle_response` gọi sang `on_request` và `on_response` để tương thích ngược cấu trúc plugin V1 với Router V2.

## Mục đích & Ý nghĩa
- Nguyên nhân khiến quảng cáo vẫn lọt qua là do:
  1. Router V2 nạp `YouTubePlugin` dưới dạng Observer (đọc dữ liệu bất đồng bộ). Do chạy bất đồng bộ, lệnh `flow.kill()` bị gọi quá trễ (sau khi mitmproxy đã đẩy gói tin đi), nên request không bị chặn thực sự.
  2. Lỗi thụt lề trong hàm `is_youtube_ad_request` vô tình gộp các điều kiện kiểm tra `doubleclick.net` và `api/stats/ads` vào bên trong nhau, dẫn đến hàm luôn trả về `False` với các tên miền quảng cáo.
- Các sửa đổi này giúp hệ thống V2 bắt và tiêu diệt các request ads chuẩn xác, kịp thời ngay trước khi gửi ra ngoài.

## Mối liên hệ
- Ảnh hưởng đến quy trình xử lý luồng HTTP (`ProxyRouter`) trong `core/router.py`.
- Tương thích trực tiếp với các script chặn ads ở `youtube_utils.py` và `youtube.py`.

## Rủi ro (Risks & Edge Cases)
- `YouTubePlugin` giờ trở thành một Mutator, nên nếu xảy ra lỗi ngoại lệ chưa xử lý, nó có thể làm chậm proxy pipeline. Tuy nhiên, logic bên trong đã được bao bọc bởi `try-except` đầy đủ.
