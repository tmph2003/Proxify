# Tích Hợp Proxify Trực Tiếp Vào Profile Gốc Của Google Chrome

## 1. Tóm tắt thay đổi
- Gỡ bỏ tham số `--user-data-dir` khỏi shortcut `Google Chrome (Proxify).lnk` trên Desktop.
- Cấu hình shortcut sử dụng trực tiếp thư mục User Data mặc định của người dùng (`%LOCALAPPDATA%\Google\Chrome\User Data`) với cờ `--proxy-server="http://127.0.0.1:8080"` và danh sách `--proxy-bypass-list`.
- Xóa bỏ thư mục profile tạm `User Data Proxify`.

## 2. Mục đích & Ý nghĩa
- **Bảo toàn 100% dữ liệu người dùng:** Khi dùng `--user-data-dir` trỏ sang thư mục khác, Chrome sẽ khởi tạo một hồ sơ trắng tinh, làm mất toàn bộ bookmarks, mật khẩu, tài khoản Google đã đăng nhập (`Default`, `Profile 1`), lịch sử duyệt web và các tiện ích mở rộng sẵn có.
- **Tối ưu trải nghiệm sử dụng:** Việc dùng profile gốc giúp người dùng mở Chrome lên là có sẵn tài khoản YouTube cá nhân, danh sách đăng ký kênh (Subscriptions) mà vẫn tận dụng được toàn bộ sức mạnh chặn quảng cáo và bóc tách dữ liệu của Proxify qua cổng 8080.
- **Giữ vững nguyên tắc cô lập hệ thống:** Chỉ định cấu hình proxy ở cấp độ ứng dụng Chrome thông qua tham số khởi chạy (CLI flags), giữ nguyên Proxy hệ thống Windows tắt (`ProxyEnable = 0`) để đảm bảo các ứng dụng khác (Zalo, game FC Online) không bị ảnh hưởng.

## 3. Mối liên hệ
- **Hệ thống Profile Chrome:** Liên kết trực tiếp với các profile `Default` và `Profile 1` trong `%LOCALAPPDATA%\Google\Chrome\User Data`.
- **Backend Proxify (`backend/proxify/server.py`):** Lắng nghe và xử lý lưu lượng YouTube từ profile gốc qua cổng 8080.

## 4. Rủi ro (Risks & Edge Cases)
- **Cơ chế Single-Instance Mutex của Chrome:** Nếu một cửa sổ Chrome đã mở sẵn trước đó không có cờ proxy, việc click shortcut sẽ chỉ gửi lệnh mở tab mới vào tiến trình cũ và cờ proxy sẽ không có hiệu lực. Để khắc phục triệt để, người dùng cần tắt hẳn toàn bộ các cửa sổ Chrome đang chạy một lần duy nhất trước khi mở shortcut này.
