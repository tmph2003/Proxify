# Cơ Chế Bật/Tắt Proxy Chrome 1-Chạm & Khôi Phục Nguyên Bản (Hot-Swap Architecture)

## 1. Tóm tắt thay đổi
- **Nâng cấp [`scripts/create_chrome_shortcuts.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/scripts/create_chrome_shortcuts.py):**
  - Bổ sung hệ thống lệnh CLI (`disable` / `off` / `restore` / `restart`, `enable` / `on`, `toggle`, `status`).
  - Thêm hàm `remove_chrome_registry_policy()` để xóa triệt để các khóa `ProxyMode`, `ProxyServer`, `ProxyBypassList` tại cả 2 nhánh `HKLM\SOFTWARE\Policies\Google\Chrome` và `HKCU\SOFTWARE\Policies\Google\Chrome`.
  - Cập nhật `update_all_chrome_shortcuts(enable_proxy_flags=False)` để gỡ bỏ hoàn toàn các tham số dòng lệnh `--proxy-server` và `--proxy-bypass-list` khỏi toàn bộ file `.lnk` của Chrome (Desktop, Taskbar, ImplicitAppShortcuts cho từng Profile, Start Menu) trong khi vẫn bảo toàn cờ `--profile-directory`.
  - Thêm hàm `restart_chrome_cleanly()` sử dụng `subprocess.Popen` với `DETACHED_PROCESS` và cờ `--restore-last-session` để khởi động lại tiến trình `chrome.exe` sạch (không còn cờ `--proxy-server` tồn đọng từ phiên cũ) mà vẫn giữ nguyên toàn bộ các tab đang mở.
- **Tích hợp bộ điều khiển Proxy 1-Chạm vào [`backend/chrome_extension/`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/manifest.json):**
  - Bổ sung quyền `"proxy"` vào [`manifest.json`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/manifest.json) (nâng phiên bản lên `1.3`).
  - Thêm bộ điều khiển `chrome.proxy.settings` và đồng bộ nhãn trạng thái (`ON` badge màu xanh lá trên thanh công cụ Chrome) trong [`background.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/background.js).
  - Thiết kế giao diện thẻ trạng thái và nút gạt **Bật / Tắt Proxy (Về nguyên bản)** ngay đầu popup trong [`popup.html`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.html) và [`popup.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.js), đồng thời kiểm tra chính xác trạng thái `levelOfControl === "not_controllable"` khi tiến trình Chrome cũ vẫn giữ cờ `--proxy-server`.

---

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để điểm nghẽn kiến trúc (Tight Coupling ở Tầng 1 & Tầng 2 của Chromium):**
  - Trước đây, `create_chrome_shortcuts.py` khóa cứng Chrome vào `127.0.0.1:8080` bằng cả **Windows Registry Group Policy** (Tầng 1) lẫn **Command-Line Flags trên Shortcut `.lnk`** (Tầng 2).
  - Do thứ tự ưu tiên của Chromium (`Group Policy > Command-line Flags > Extension API > System Proxy`), khi tiến trình `chrome.exe` đã được mở từ trước với cờ `--proxy-server="http://127.0.0.1:8080"`, thuộc tính `details.levelOfControl` của `chrome.proxy.settings` sẽ bị khóa ở `"not_controllable"`, khiến lệnh tắt từ Extension bị bỏ qua cho tới khi tiến trình `chrome.exe` cũ được khởi chạy lại mà không có cờ `--proxy-server`.
- **Chuyển dịch quyền điều khiển sang Tầng 3 (`chrome.proxy` API):**
  - Sau khi dọn sạch Tầng 1 (Registry Policy), Tầng 2 (Shortcut Flags) và khởi chạy lại tiến trình `chrome.exe` sạch (qua `--restore-last-session`), tiện ích `Proxify Helper` nắm toàn quyền điều khiển Proxy ở Tầng 3.
  - Từ thời điểm này, người dùng có thể **Hot-Swap (Bật/Tắt tức thì)** chỉ bằng 1 cú click chuột ngay trên thanh công cụ Chrome mà không bao giờ cần khởi động lại trình duyệt nữa.

---

## 3. Mối liên hệ
- **[`scripts/create_chrome_shortcuts.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/scripts/create_chrome_shortcuts.py):** Đóng vai trò công cụ quản trị CLI để dọn sạch (`disable` / `restart`) hoặc bật/tắt (`toggle`) Registry Policy của Chrome khi cần thiết.
- **[`backend/chrome_extension/manifest.json`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/manifest.json), [`background.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/background.js), [`popup.html`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.html), [`popup.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/popup.js):** Giao tiếp trực tiếp với nhân mạng của Chrome thông qua `chrome.proxy.settings` và định tuyến lưu lượng về Mitmproxy Core (`127.0.0.1:8080`) kèm danh sách `DEFAULT_PROXY_BYPASS_LIST` đồng nhất với cấu hình hệ thống.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Tiến trình Chrome chạy ngầm giữ cờ `--proxy-server` cũ:** Khi người dùng chỉ tắt một cửa sổ Chrome nhưng vẫn còn cửa sổ khác hoặc tiến trình chạy ngầm (System Tray), tiến trình gốc `chrome.exe` vẫn giữ `CommandLine` cũ có chứa `--proxy-server`. Giải pháp `python scripts/create_chrome_shortcuts.py restart` đã xử lý triệt để trường hợp này bằng cách đóng toàn bộ `chrome.exe` cũ và mở lại với `--restore-last-session`.
- **Xung đột với Extension quản lý Proxy khác:** Nếu người dùng cài thêm một tiện ích proxy khác (như ZeroOmega/FoxyProxy) có quyền ưu tiên cao hơn, `details.levelOfControl` sẽ trả về `controlled_by_other_extensions`. Giao diện `popup.js` đã bắt trường hợp này để cảnh báo rõ ràng cho người dùng.
