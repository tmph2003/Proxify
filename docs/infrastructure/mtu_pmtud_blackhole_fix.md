# Khắc Phục Hiện Tượng PMTUD Black Hole Gây Treo Tải YouTube (MTU Mismatch Fix)

## 1. Tóm tắt thay đổi
- Thực hiện kiểm tra phân mảnh gói tin thực tế (Don't Fragment ping test) và phát hiện giới hạn MTU vật lý của đường truyền qua router phụ TP-Link/PPPoE FPT là **1450 bytes**.
- Toàn bộ gói tin có kích thước từ 1452 đến 1500 bytes đều bị drop 100% khi đi qua router.
- Cấu hình lại MTU chuẩn **1420 bytes** cho card mạng `Wi-Fi` trên cả hai giao thức IPv4 và IPv6 bằng lệnh:
  ```powershell
  netsh interface ipv4 set subinterface "Wi-Fi" mtu=1420 store=persistent
  netsh interface ipv6 set subinterface "Wi-Fi" mtu=1420 store=persistent
  ```

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để lỗi "YouTube load mãi không được":**
  - Khi MTU trên Windows để mặc định 1500 (IPv4) và 1492 (IPv6), máy tính đàm phán MSS kích thước lớn với máy chủ YouTube/Google.
  - Khi tải các file mã nguồn JavaScript nặng hoặc video chunks từ YouTube, máy chủ gửi các frame dữ liệu đầy đủ (1500 bytes).
  - Các gói tin này bị chặn đứng hoàn toàn tại router TP-Link/PPPoE do cờ `DF` (Don't Fragment) được bật. Router không phân mảnh được mà cũng không gửi lại thông điệp ICMP (Path MTU Discovery Black Hole).
  - Kết quả là trình duyệt Chrome bị treo vĩnh viễn ở trạng thái chờ gói tin bị mất (stalled/buffering spinner xoay mãi).
- **Ý nghĩa:** Hạ MTU về 1420 đảm bảo mọi kết nối TCP/UDP khi bắt tay (handshake) đều báo cho máy chủ từ xa chỉ gửi các gói tối đa 1420 bytes, loại bỏ hoàn toàn hiện tượng rớt gói tin lớn.

## 3. Mối liên hệ
- Tác động trực tiếp lên tầng Network (Tầng 3) và Transport (Tầng 4) của toàn bộ hệ thống Windows.
- Giúp các dịch vụ truyền tải dữ liệu lớn (YouTube video streaming, file download, tải trang SPA) hoạt động tức thì mà không bị nghẽn cổ chai.

## 4. Rủi ro (Risks & Edge Cases)
- **Các socket TCP đã mở sẵn trước đó:** Các tiến trình đã mở socket trước khi đổi MTU (như cửa sổ Chrome đang chạy từ trước) vẫn giữ giá trị MSS cũ cho đến khi đóng tab hoặc khởi động lại trình duyệt. Do đó, bắt buộc người dùng cần tắt hẳn trình duyệt và mở lại để áp dụng giá trị MTU mới.
