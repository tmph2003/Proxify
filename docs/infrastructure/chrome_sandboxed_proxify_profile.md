# Tài Liệu Cô Lập Trình Duyệt Proxify Bằng User Data Profile Riêng Biệt

## 1. Tóm tắt thay đổi
- Khởi động lại cụm container Docker (`proxify_app`, `proxify_db`, `proxify_ui`) ở trạng thái healthy.
- Thiết lập lại shortcut ngoài Desktop: `Google Chrome (Proxify).lnk` với tham số `--user-data-dir="C:\Users\Administrator\AppData\Local\Google\Chrome\User Data Proxify"`, `--proxy-server="http://127.0.0.1:8080"` và `--proxy-bypass-list`.
- Giữ nguyên Proxy hệ thống Windows tắt (`ProxyEnable = 0`) và icon Chrome dưới thanh Taskbar ở trạng thái nguyên bản 100% không proxy.

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để vấn đề xung đột tiến trình Chrome (Single-Instance Mutex):** Trong Windows, nếu Chrome đang mở bằng profile mặc định, việc click một shortcut có cờ `--proxy-server` sẽ chỉ mở thêm tab trên tiến trình cũ (vốn không dùng proxy) hoặc ngược lại gây ô nhiễm proxy cho toàn bộ các cửa sổ Chrome khác.
- **Cô lập tuyệt đối (Sandboxing):** Việc chỉ định `--user-data-dir` riêng biệt giúp tạo ra một phiên làm việc độc lập hoàn toàn cho Proxify. Người dùng có thể mở song song:
  - Chrome thường (dưới Taskbar): Dùng làm việc, lướt web tốc độ gốc, chơi FC Online ping 2ms, không dính proxy.
  - Chrome Proxify (ngoài Desktop): Dùng để xem YouTube chặn quảng cáo và bóc tách dữ liệu MITM qua cổng 8080.

## 3. Mối liên hệ
- **Mitmproxy Server (`backend/proxify/server.py`):** Tiếp nhận các kết nối từ profile Proxify Chrome trên cổng 8080.
- **YouTube Plugin (`backend/extensions/youtube/plugin.py`):** Bóc tách quảng cáo và nhúng script anti-AFK khi người dùng xem YouTube trong profile này.
- **Windows System Proxy:** Hoàn toàn tách rời, không can thiệp vào `HKCU\...\Internet Settings`.

## 4. Rủi ro (Risks & Edge Cases)
- **Tài khoản và Cookie:** Vì là một profile Chrome mới, lần đầu mở `Google Chrome (Proxify)`, người dùng sẽ cần đăng nhập lại tài khoản Google trên cửa sổ này nếu muốn đồng bộ lịch sử xem.
- **Chứng chỉ CA:** Profile mới vẫn kế thừa chứng chỉ gốc `mitmproxy` từ Windows Certificate Store nên không bị lỗi cảnh báo SSL/TLS `NET::ERR_CERT_AUTHORITY_INVALID`.
