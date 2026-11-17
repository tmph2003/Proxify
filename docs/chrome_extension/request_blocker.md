# 🚫 Chrome Extension — Custom Request Blocker (`declarativeNetRequest`)

## 1. Tóm tắt thay đổi
Bổ sung tính năng **Chặn Request Tùy Chỉnh (Custom Request Blocker)** hoạt động trực tiếp trên trình duyệt Chrome vào tiện ích mở rộng tại `backend/chrome_extension/`:
- **`manifest.json`** (nâng cấp lên `v2.1`):
  - Cấp thêm quyền `"declarativeNetRequest"` (chặn mạng ở tầng nhân trình duyệt mà không cần quyền đọc nội dung trang) và `"tabs"` (để nhận diện chính xác `tab.url` của tab đang mở trong Popup).
- **`background.js`**:
  - Xây dựng bộ chuyển đổi `normalizePatternToUrlFilter()` và `buildDnrRules()` biến đổi các mẫu Domain / URL Pattern của người dùng (như `doubleclick.net`, `*.doubleclick.net`, `example.com/ads/*`, `*://example.com/ads/*`, `/api/telemetry`) sang chuẩn `urlFilter` của Chrome `declarativeNetRequest`.
  - Cài đặt cơ chế đồng bộ tuần tự `syncDynamicBlockRules()` qua `chrome.declarativeNetRequest.updateDynamicRules()` (sử dụng dải ID riêng từ `10001` trở đi để không xung đột với các rule khác), tự động kích hoạt khi cài đặt (`onInstalled`), khởi động trình duyệt (`onStartup`), thay đổi `chrome.storage.local` (`onChanged`), hoặc nhận thông điệp `SYNC_BLOCK_RULES`.
  - Cập nhật Badge thông minh trên thanh công cụ: hiển thị `ON` (màu xanh) khi đang bật Proxy, hoặc hiển thị số lượng quy tắc chặn đang hoạt động (màu cam) khi tắt Proxy.
- **`popup.html` & `popup.js`**:
  - Thêm thẻ điều khiển **🚫 Chặn Request (Blocker)** ngay trên giao diện Popup: công tắc tổng (Master Toggle) để tạm dừng/bật lại mà không mất danh sách quy tắc, form thêm nhanh Domain / URL Pattern, nút **Chặn nhanh domain của Tab hiện tại**, bật/tắt hoặc xóa từng quy tắc riêng lẻ, và nút xóa toàn bộ quy tắc.
  - Chuẩn hóa toàn bộ HTML/JS theo hướng tiếp cận hiện đại (Semantic `<form>`, `<label>`, `aria-invalid`, `aria-live`, dùng `textContent` / DOM API thay cho `innerHTML` để triệt tiêu hoàn toàn nguy cơ XSS).

## 2. Mục đích & Ý nghĩa
- **Hiệu năng tối đa & Độc lập với Proxy Server**:
  - Việc sử dụng `chrome.declarativeNetRequest` (Dynamic Rules) giúp Chrome hủy gói tin ngay từ tầng Network Stack của trình duyệt trước khi mở kết nối TCP/TLS. Các request rác (quảng cáo, tracking, telemetry, tài nguyên nặng) bị chặn tức thì ngay cả khi người dùng tắt Proxy (`DIRECT`) và hoàn toàn không tiêu tốn CPU/RAM của tiến trình `mitmproxy` phía sau.
- **Bảo toàn kiến trúc Clean Architecture**:
  - Tách biệt rõ ràng trách nhiệm: Tầng Browser Client (`chrome_extension`) đảm nhiệm lọc/chặn các request không mong muốn từ phía trình duyệt, trong khi tầng Proxy Core (`backend/proxify/`) chỉ tập trung giải mã TLS và ghi nhận các gói tin thực sự cần phân tích.

## 3. Mối liên hệ
- **`backend/chrome_extension/popup.js` ↔ `backend/chrome_extension/background.js`**:
  - Giao tiếp qua `chrome.storage.local` (`blockerEnabled`, `blockRules`) và kênh message bất đồng bộ `chrome.runtime.sendMessage({ type: "SYNC_BLOCK_RULES" })`.
- **Bảo vệ Control Plane (`dashboard.py`)**:
  - Hàm `cleanUserPattern()` trong `popup.js` tích hợp chốt chặn an toàn không cho phép người dùng vô tình thêm `localhost` hoặc `127.0.0.1` vào danh sách đen, đảm bảo kết nối từ Extension tới Dashboard API (`127.0.0.1:8888`) và cổng Proxy (`127.0.0.1:8080`) không bao giờ bị tự khóa.

## 4. Rủi ro (Risks & Edge Cases)
- **Giới hạn ký tự ASCII của `urlFilter` và Punycode**:
  - Chrome `declarativeNetRequest` yêu cầu trường `condition.urlFilter` chỉ chứa ký tự ASCII. Nếu người dùng dán tên miền quốc tế hóa (IDN / tiếng Việt có dấu), `normalizePatternToUrlFilter()` đã tự động chuyển đổi sang dạng Punycode thông qua `new URL()` hoặc lọc bỏ ký tự ngoài bảng mã ASCII để tránh làm gãy toàn bộ batch `updateDynamicRules`.
- **Giới hạn số lượng Dynamic Rules của Chrome**:
  - Manifest V3 giới hạn tối đa `30,000` dynamic rules cho mỗi extension — hoàn toàn dư dả cho nhu cầu cấu hình tùy chỉnh thủ công trên Popup.
- **Cập nhật quyền khi nâng cấp Extension**:
  - Vì `manifest.json` bổ sung quyền `"declarativeNetRequest"` và `"tabs"`, người dùng đang cài bản cũ cần mở `chrome://extensions` và bấm nút **Reload (🔄)** tại thẻ **Proxify Helper** để Chrome nạp Service Worker và quyền mới.
