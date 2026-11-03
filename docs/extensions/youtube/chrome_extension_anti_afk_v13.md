# Chrome Extension & Proxy Watchdog — Sửa lỗi kẹt thanh tìm kiếm YouTube (v1.6)

## Tóm tắt thay đổi
- **Tầng Chrome Extension (`backend/chrome_extension/manifest.json` & `private/chrome_extension_fb/manifest.json`)**:
  - Nâng cấp lên v1.6: Gỡ bỏ hoàn toàn `youtube_anti_afk.js` khỏi `content_scripts` của Chrome Extension để Extension chỉ đảm nhận đúng chức năng Bật/Tắt Proxy 1-Click và đồng bộ Cookie Facebook, tuyệt đối không tự tiêm script can thiệp vào DOM của YouTube.
- **Tầng Proxy (`crates/ext-youtube/src/lib.rs`)**:
  - Xóa bỏ hoàn toàn lệnh bắn sự kiện giả `document.dispatchEvent(new MouseEvent("mousemove", ...))` và các global capture listener `["pointerdown", "mousedown", "keydown", "touchstart", "click"]` trong `YOUTUBE_WATCHDOG_JS`.
  - Xóa bỏ khối code nối `YOUTUBE_WATCHDOG_JS` vào các bundle tĩnh được cache dài hạn (`desktop_polymer.js` và `base.js`).

## Mục đích & Ý nghĩa
- **Nguyên nhân gốc rễ làm thanh tìm kiếm không tắt được**:
  - Trong cả `youtube_anti_afk.js` (hàm `simulateActivity`) và `YOUTUBE_WATCHDOG_JS` (hàm `keepLactFresh` được kích hoạt ngay trên mọi sự kiện `pointerdown`/`mousedown`/`click`), code đã bắn sự kiện giả `MouseEvent("mousemove")` vào `document` ở tọa độ `(10, 10)` hoặc `(100..300, 100..300)`.
  - Khi danh sách gợi ý tìm kiếm của YouTube (`yt-searchbox`) nhận được sự kiện `mousemove` giả lập này (khiến một dòng gợi ý tìm kiếm luôn ở trạng thái hover màu xám như trong ảnh chụp màn hình), component `yt-searchbox` đánh dấu trạng thái con trỏ chuột đang nằm trên bảng gợi ý và chặn sự kiện `blur` của ô `<input>`, làm bảng gợi ý tìm kiếm không bao giờ đóng lại khi click ra ngoài.
- Việc loại bỏ hoàn toàn `MouseEvent("mousemove")` và gỡ bỏ `youtube_anti_afk.js` khỏi Chrome Extension giúp thanh tìm kiếm của YouTube đóng mở tự nhiên 100%, trong khi cơ chế chống AFK vẫn hoạt động qua việc cập nhật trực tiếp biến `window._lact = Date.now()`.

## Mối liên hệ
- `backend/chrome_extension/manifest.json` & `private/chrome_extension_fb/manifest.json`: Tệp cấu hình Chrome Extension v1.6.
- `crates/ext-youtube/src/lib.rs`: Chứa `YOUTUBE_WATCHDOG_JS` và `mutate_response()`.

## Rủi ro (Risks & Edge Cases)
- **Bộ nhớ đệm (Disk Cache) của trình duyệt**: Nếu trình duyệt trước đó đã lưu cache file `base.js` hoặc `desktop_polymer.js` có gắn bản Watchdog cũ, người dùng cần nhấn `Ctrl + Shift + R` (Hard Reload) một lần trên tab YouTube sau khi Reload tiện ích.
