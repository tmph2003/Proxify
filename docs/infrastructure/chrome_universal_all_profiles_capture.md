# Cấu Hình Chrome-Wide Universal Capture Cho Mọi Profile (Chế Độ 1)

## 1. Tóm tắt thay đổi
- **Tại [`backend/proxify/server.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py):**
  - Gỡ bỏ danh sách cứng `DEFAULT_TARGET_DOMAINS` trong `allow_hosts` của Mitmproxy để kích hoạt **Universal Capture** (bắt và giải mã toàn bộ lưu lượng HTTP/HTTPS/WebSocket từ mọi trang web mặc định, chỉ lọc theo `INTERCEPT_DOMAINS` nếu biến môi trường này được cấu hình tường minh).
  - Rút gọn `explicit_bypasses` và `IGNORE_HOSTS` mặc định: chỉ giữ lại các luồng video CDN băng thông lớn (`googlevideo.com`, `c.youtube.com`) và các endpoint xác thực/telemetry hệ thống nhạy cảm (`accounts.google.com`, `accounts.youtube.com`, `clients*.google.com`, `gvt1-3.com`, `1e100.net`, `nel.goog`, `msftncsi.com`, `windowsupdate.com`).
  - Loại bỏ `sunhouse.com.vn` và toàn bộ các tên miền web phổ thông ra khỏi danh sách `IGNORE_HOSTS`.
- **Tại [`.env`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/.env) và [`docker-compose.yml`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml):**
  - Đồng bộ hóa biến môi trường `IGNORE_HOSTS` theo cấu hình Universal Capture mới.
- **Tại [`scripts/create_chrome_shortcuts.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/scripts/create_chrome_shortcuts.py):**
  - Bổ sung hàm `apply_chrome_registry_policy()` để thiết lập trực tiếp chính sách Proxy cấp ứng dụng của Google Chrome trong Windows Registry (`HKLM\SOFTWARE\Policies\Google\Chrome` và `HKCU\SOFTWARE\Policies\Google\Chrome`: `ProxyMode = fixed_servers`, `ProxyServer = 127.0.0.1:8080`, `ProxyBypassList`).
  - Nâng cấp `update_all_chrome_shortcuts()` để quét đệ quy và cập nhật cờ `--proxy-server="http://127.0.0.1:8080"` trên **tất cả** các shortcut Chrome bao gồm: Desktop, Taskbar, Start Menu, và đặc biệt là thư mục `ImplicitAppShortcuts` (nơi chứa các shortcut gắn riêng với từng Profile như `--profile-directory="Profile 1"`), đồng thời gỡ bỏ `*.sunhouse.com.vn` khỏi `--proxy-bypass-list`.

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để bài toán Đa Profile Chrome (Zero-Click Multi-Profile):**
  - Trước đây, việc dựa vào một file shortcut đơn lẻ ngoài Desktop khiến các shortcut riêng của từng Profile (`Profile 1`, `Profile 2`,...) hoặc việc mở Chrome từ Start Menu / click link từ ứng dụng khác bị lọt lưới không đi qua Proxify.
  - Kết hợp giữa **Chrome Native Registry Policy** và đồng bộ toàn bộ `ImplicitAppShortcuts` giúp cưỡng chế 100% mọi tiến trình và mọi Profile của `chrome.exe` luôn định tuyến qua cổng `8080` của Proxify, bất kể người dùng khởi chạy Chrome từ đâu hay dùng Profile nào.
- **Mở khóa toàn bộ lưu lượng trên Dashboard (Universal Capture):**
  - Gỡ bỏ `allow_hosts` chỉ giới hạn 8 domain trước đây giúp mọi request/response từ tất cả các trang web (bao gồm cả các hệ thống nội bộ/công việc trên `Profile 1`) đều hiển thị đầy đủ theo thời gian thực trên giao diện Dashboard (`http://localhost:8888`).
- **Bảo toàn cô lập với hệ điều hành và Game:**
  - Chính sách `SOFTWARE\Policies\Google\Chrome` chỉ có hiệu lực đối với trình duyệt Google Chrome. Proxy hệ thống của Windows (`ProxyEnable = 0`) vẫn tắt 100%, đảm bảo các ứng dụng ngoài Chrome (Game FC Online, Zalo PC, dịch vụ hệ thống) đi thẳng qua card mạng vật lý với độ trễ bằng 0.

## 3. Mối liên hệ
- **[`backend/proxify/server.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py) & [`backend/proxify/core/router.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/core/router.py):** Tiếp nhận, giải mã TLS và đẩy toàn bộ lưu lượng từ mọi Profile Chrome lên `V1GlobalObserver` (WebSocket Dashboard & PostgreSQL Database) trong khi vẫn giữ cơ chế stream trực tiếp các file media/video lớn (`_STREAM_EXTENSIONS`, `_STREAM_DOMAINS`).
- **[`scripts/create_chrome_shortcuts.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/scripts/create_chrome_shortcuts.py):** Tự động hóa việc áp dụng Registry Policy và cập nhật toàn bộ shortcut `.lnk` của Chrome trên Windows.

## 4. Rủi ro (Risks & Edge Cases)
- **Tăng lưu lượng ghi Database:** Khi bắt toàn bộ các trang web, số lượng request đẩy về Dashboard và PostgreSQL sẽ nhiều hơn so với khi chỉ bắt 3 nền tảng. Tuy nhiên, hệ thống đã có sẵn `PollingEndpointFilter`, cơ chế streaming file tĩnh trong `ProxyRouter` và chính sách dọn dẹp tự động `RECORD_RETENTION_DAYS=7` để kiểm soát dung lượng.
- **Hiệu lực trên tiến trình Chrome đang mở:** Đối với các cửa sổ Chrome đã mở sẵn với cấu hình `--proxy-bypass-list` cũ trên RAM trước khi chạy script, nếu người dùng muốn xóa bỏ hoàn toàn danh sách bypass cũ ngay lập tức thì chỉ cần vào `chrome://policy` bấm **Reload policies** hoặc khởi động lại trình duyệt.
