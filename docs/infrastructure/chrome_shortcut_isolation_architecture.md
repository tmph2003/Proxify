# Kiến trúc Cô lập Chrome qua Shortcut (Isolated Shortcut-Based Proxying)

## 1. Tóm tắt thay đổi
- **Tạo và cập nhật Shortcut Chrome với tham số Proxy chuyên biệt**:
  - Tạo biểu tượng **`Google Chrome (Proxify).lnk`** trên Desktop và cập nhật shortcut Chrome trên thanh Taskbar.
  - Cấu hình cờ khởi động:
    `--proxy-server="http://127.0.0.1:8080" --proxy-bypass-list="localhost;127.0.0.1;<local>;192.168.*;10.*;172.16.*;*.sunhouse.com.vn;14.232.214.249;*.zadn.vn;*.zing.vn;mail.google.com;chat.google.com;accounts.google.com;accounts.youtube.com"`
- **Tắt 100% Proxy hệ thống của Windows (`ProxyEnable = 0`)**:
  - Windows giữ nguyên trạng thái không dùng proxy.
  - Toàn bộ các ứng dụng khác (Game FC Online, Garena, Steam, Zalo PC, Windows Update, Edge) kết nối trực tiếp 100% ra card mạng vật lý.
- **Tối ưu DNS cho Container Docker (`docker-compose.yml`)**:
  - Chuyển DNS của container `proxify_app` từ DNS nội bộ router `192.168.100.1` sang DNS công cộng tốc độ cao `8.8.8.8` và `1.1.1.1`, giảm độ trễ phân giải tên miền từ 275ms xuống dưới 20ms cho các kết nối outbound từ proxy.

---

## 2. Mục đích & Ý nghĩa
- **Tách bạch hoàn toàn ranh giới giữa Trình duyệt và Hệ điều hành (Decoupling Boundary)**:
  - Người dùng chỉ có nhu cầu sử dụng Proxify để chặn quảng cáo YouTube và trích xuất request trên Google Chrome.
  - Việc bật Proxy toàn hệ thống trước đây khiến tất cả các ứng dụng nền, game online, dịch vụ cập nhật bị ép đi qua cổng 8080, gây ra tình trạng nghẽn cổ chai, lag phím, và mất mạng khi container restart.
  - Việc đưa cấu hình Proxy vào Shortcut khởi động của Chrome giúp:
    1. Trình duyệt Chrome tự động kết nối qua Proxify mà không cần cài thêm extension hay sửa registry chính sách hệ thống.
    2. Các ứng dụng khác của máy tính (đặc biệt là Game FC Online) hoạt động độc lập 100% trên mạng gốc, không bị ảnh hưởng bởi Docker hay Proxy.

---

## 3. Mối liên hệ
- **Hệ thống Desktop & Taskbar**: Shortcut `Google Chrome (Proxify).lnk` và shortcut Taskbar.
- **`docker-compose.yml`**: Cấu hình DNS `8.8.8.8` & `1.1.1.1` cho `proxify_app`.
- **`scripts/create_chrome_shortcuts.py`**: Script tự động sinh shortcut tương thích Windows Shell API.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro**: Nếu Chrome đang chạy sẵn ở chế độ không proxy (được mở trước đó bằng cách khác), việc mở thêm cửa sổ mới bằng shortcut có thể kế thừa tiến trình cũ nếu không tắt hẳn tiến trình Chrome trước đó.
- **Biện pháp xử lý**: Khi muốn chuyển sang chế độ Proxify lần đầu, người dùng chỉ cần tắt hẳn Chrome (đóng hết các cửa sổ) rồi nhấp vào shortcut là xong.
