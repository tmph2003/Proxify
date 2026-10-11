# Tích Hợp Proxify Vào Shortcut Google Chrome Trên Thanh Taskbar

## 1. Tóm tắt thay đổi
- Cấu hình trực tiếp tham số `--proxy-server="http://127.0.0.1:8080"` và `--proxy-bypass-list` vào shortcut Google Chrome ghim trên thanh Taskbar (`%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Google Chrome.lnk`).
- Đồng bộ hóa cả hai lối tắt (Taskbar và Desktop) về cùng một cấu hình proxy ứng dụng mà không cần thay đổi thư mục profile của người dùng.

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để thói quen người dùng:** Người dùng có xu hướng click icon Chrome ghim sẵn trên thanh Taskbar thay vì tìm kiếm icon ngoài Desktop. Khi icon Taskbar không có tham số proxy, Chrome sẽ kết nối trực tiếp ra ngoài và hiển thị đầy đủ quảng cáo.
- **Bảo toàn trải nghiệm và tài nguyên:** Giữ nguyên 100% dữ liệu đăng nhập, tài khoản YouTube và lịch sử xem của người dùng trong profile gốc.
- **Cách ly tuyệt đối:** Không can thiệp vào Proxy của hệ thống Windows (`ProxyEnable = 0`). Chỉ duy nhất trình duyệt Chrome đi qua Proxify, mọi phần mềm khác (Zalo, game FC Online) chạy trực tiếp với đường truyền card mạng tối ưu.

## 3. Mối liên hệ
- **Mitmproxy Server (`backend/proxify/server.py`):** Nhận lưu lượng HTTP/HTTPS từ Chrome trên cổng 8080 để lọc quảng cáo YouTube và bóc tách dữ liệu.
- **YouTube Plugin (`backend/extensions/youtube/plugin.py`):** Triệt tiêu hoàn toàn các khung quảng cáo (Yellow ad bar, Pre-roll/Mid-roll ads).

## 4. Rủi ro (Risks & Edge Cases)
- **Cơ chế Single-Instance Mutex của Chrome:** Nếu tiến trình Chrome cũ đang mở mà không có cờ proxy, việc click icon Taskbar sẽ chỉ mở thêm tab trên tiến trình cũ. Bắt buộc người dùng phải đóng hoàn toàn tất cả cửa sổ Chrome một lần duy nhất trước khi mở lại từ Taskbar.
