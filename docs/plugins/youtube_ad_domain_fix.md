# Tài liệu: Sửa lỗi không chặn được quảng cáo YouTube (doubleclick.net)

## Tóm tắt thay đổi
- **`proxify/utils/youtube_utils.py`**: Thay đổi logic của hàm `is_youtube_ad_request`. Thêm điều kiện kiểm tra `doubleclick.net` vào lệnh `if` kiểm tra nhanh đầu hàm. Nếu domain không có `youtube.com`, không có `googlevideo.com`, URL không có `youtubei` và domain KHÔNG CÓ `doubleclick.net` thì mới return `False`.
- **`proxify/plugins/youtube.py`**: 
  - Thêm `doubleclick.net` vào danh sách `target_domains`.
  - Cập nhật lại câu lệnh lọc domain tĩnh ở phần `Fast skip` trong `on_request` để cho phép `doubleclick.net` lọt qua và đi vào logic kiểm tra quảng cáo.

## Mục đích & Ý nghĩa
- **Sửa lỗi không nhận diện được Request:** Gần đây YouTube đã thay đổi mạnh việc phân phối quảng cáo qua domain trung gian như `doubleclick.net`. Trong phiên bản cũ, cả Plugin và Utils đều mặc định "bỏ qua (Fast skip)" tất cả các luồng mạng nếu domain không chứa chữ `youtube` hay `googlevideo`. Điều này vô tình vứt bỏ luôn cả request báo cáo quảng cáo (`/api/stats/ads`) gửi đến Google/Doubleclick.
- Việc bổ sung `doubleclick.net` vào màng lọc cho phép hệ thống "bắt" và tiêu diệt các request quảng cáo này, giúp tính năng YouTube Adblock hoạt động ổn định trở lại.

## Mối liên hệ
- Lỗi này liên quan trực tiếp đến hệ thống `Plugin Registry` (`proxify/plugins/registry.py`) và `Capture Addon` (`proxify/capture_addon.py`), vì các file này chỉ cấp luồng (flow) cho plugin YouTube nếu tên miền khớp với `target_domains`.

## Rủi ro (Risks & Edge Cases)
- `doubleclick.net` là mạng quảng cáo chung của Google. Việc thêm nó vào Plugin YouTube có nghĩa là bất kỳ khi nào người dùng lướt web (không chỉ riêng YouTube) mà sinh ra luồng doubleclick, luồng đó sẽ bị Plugin YouTube "hỏi thăm". Tuy nhiên, do logic trong `is_youtube_ad_request` đã kiểm tra kỹ đuôi `/api/stats/ads`, rủi ro chặn nhầm quảng cáo của các trang web khác (nếu người dùng muốn xem) là khá thấp. Tuy nhiên cần lưu ý nếu hiệu năng bị giảm sút nhẹ do plugin YouTube phải quét thêm một lượng request rác.
