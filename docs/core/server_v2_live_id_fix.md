# Tài liệu: Sửa lỗi "LIVE" hiển thị sai lệch khi Bật Ghi DB và Lọc Tên Miền

## Tóm tắt thay đổi
- Sửa lỗi trong `proxify/server_v2.py`:
  1. Cập nhật `V1GlobalObserver.handle_response`: Thay vì ép cứng `db_save=True` cho tất cả các luồng mạng (flows), giờ đây nó sẽ đọc cấu hình `db_integration_enabled` từ bộ nhớ Storage. Nếu DB đang bật, nó tiếp tục kiểm tra mảng `db_allowed_domains` (để lọc tên miền nếu user có cài đặt lọc).
  2. Thêm logic đăng ký sự kiện (subscribe) `db_row_created` trên `v1_bus` (`proxify.core.events.bus`). Khi có sự kiện cắm DB thành công, hệ thống sẽ tự động broadcast gói tin `update_id` qua WebSocket tới Dashboard.

## Mục đích & Ý nghĩa
- Khắc phục sự cố Dashboard luôn hiển thị "LIVE" ngay cả khi tính năng Bật ghi Database (Ghi DB: BẬT) đã kích hoạt, khiến người dùng nghĩ rằng hệ thống không lưu vào DB.
- Sửa lỗi "ghi đè": Phiên bản V2 cũ bỏ qua các cấu hình Ghi DB và Lọc domain trên giao diện UI, dẫn đến tình trạng rác DB vì tất cả request bị đổ dồn vào hàng đợi.

## Mối liên hệ
- Lỗi này nằm trong cơ chế tương thích ngược (v1) được chạy trên V2 (`server_v2.py`) khi kết nối với `DashboardBroadcaster` và `DatabaseWriter` (thuộc thư mục `proxify/core/listeners.py`).

## Rủi ro (Risks & Edge Cases)
- Sự kiện `db_row_created` liên tục được đẩy (fire) lên qua WebSocket, có thể gây tải nhẹ cho socket nếu lượng Request quá lớn (vài nghìn rq/s). Tuy nhiên, vì V1 vốn đã thiết kế như vậy nên thay đổi này chỉ nhằm mục đích đảm bảo tính toàn vẹn trạng thái mà không tăng rủi ro so với thiết kế gốc.
