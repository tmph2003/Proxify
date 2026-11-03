# Tài Liệu Kỹ Thuật: Nâng Cấp Hệ Thống Bypass YouTube Auto-Pause (Anti-AFK) & Dọn Dẹp Enforcement Modal

## 1. Tóm tắt thay đổi
Bản cập nhật này giải quyết triệt để hiện tượng YouTube tự động tạm dừng phát nhạc/video kèm thông báo **"Video đã tạm dừng. Tiếp tục xem? (Có)"** (`Video paused. Continue watching?`) khi treo máy hoặc nghe playlist dài:

1. **Ở tầng MITM Proxy (`crates/ext-youtube/src/lib.rs`)**:
   - **Vô hiệu hóa ServiceWorker (`sw.js`) & Ép tải mới HTML (`/watch`)**: Trả về script tự hủy đăng ký (`self.registration.unregister()`) kèm header `Clear-Site-Data: "storage"` khi trình duyệt gọi `/sw.js`, đồng thời loại bỏ `if-none-match` / `if-modified-since` trên trang `/watch` để ngăn ServiceWorker của YouTube phục vụ HTML từ App-Shell Cache (vốn làm mất script Watchdog được tiêm vào HTML).
   - **Tiêm Watchdog trực tiếp vào Core Player JS (`desktop_polymer.js` / `base.js`)**: Đăng ký `register_stream_exclusion` cho `desktop_polymer` và `/base.js`, cho phép `YouTubePlugin` chèn `YOUTUBE_WATCHDOG_JS` ngay đầu file script chính của YouTube.
   - **Mở rộng bộ lọc JSON Innertube (`clean_youtube_json_data`)**:
     - Vô hiệu hóa thêm `youThereData` lồng bên trong `youThereRenderer.configData.youThereData` và đặt `showPausedActions = false`.
     - Loại bỏ `bkaEnforcementMessageViewModel` và `enforcementMessageViewModel` trong `auxiliaryUi.messageRenderers` cũng như `messages` (ngăn chặn popup chặn trình phát của YouTube).
   - **Nâng cấp `YOUTUBE_WATCHDOG_JS`**:
     - Giả lập hoạt động người dùng định kỳ mỗi 5 giây (`window._lact = Date.now()`, `window.yt.config_._lact = Date.now()`, và bắn sự kiện `MouseEvent("mousemove")`).
     - Theo dõi chính xác hành vi tạm dừng chủ động của người dùng (`userPaused` qua sự kiện `isTrusted` click/phím Space/`k`).
     - Bắt trực tiếp sự kiện `pause` ở giai đoạn capture trên thẻ `<video>`: Nếu video bị YouTube tự động dừng mà không có thao tác từ người dùng trong 800ms trước đó, lập tức đóng hộp thoại (`dismissDialog`) và gọi `video.play()` / `movie_player.playVideo()` chỉ sau 80ms.
     - Hỗ trợ đóng cả phần tử `tp-yt-paper-dialog`, `yt-confirm-dialog-renderer`, `yt-you-there-renderer` và gỡ lớp phủ mờ `tp-yt-iron-overlay-backdrop`.

2. **Ở tầng Chrome Extension (`backend/chrome_extension/`)**:
   - Thêm Content Script [`youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/youtube_anti_afk.js) chạy ở `world: "MAIN"` và `run_at: "document_start"` trong [`manifest.json`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/manifest.json) cho `*://*.youtube.com/*`. Đảm bảo cơ chế Anti-AFK luôn hoạt động 100% bất kể trạng thái cache của trình duyệt hay điều hướng SPA.

3. **Ở tầng Lưu trữ Core (`crates/proxify-core/src/storage.rs`)**:
   - Lọc bỏ byte null (`\0` / `0x00`) trong `request_body` và `response_body` trước khi thực thi batch `INSERT INTO public.requests` để tránh lỗi `invalid byte sequence for encoding "UTF8": 0x00` của PostgreSQL khi lưu các gói tin protobuf/binary của YouTube.

---

## 2. Mục đích & Ý nghĩa
- **Giải quyết vấn đề cốt lõi**: Khi người dùng mở danh sách phát (Mix/Playlist) trên YouTube (đặc biệt qua điều hướng SPA hoặc khi ServiceWorker đã lưu cache HTML từ trước), YouTube kích hoạt bộ đếm nhàn rỗi (`youThereRenderer` / `_lact`) và tự động gọi `.pause()` trên `<video>`, hiển thị popup *"Video đã tạm dừng. Tiếp tục xem?"*.
- **Phòng thủ đa lớp (Defense-in-Depth)**:
  1. **Lớp 1 (Network JSON Stripping)**: Xóa/vô hiệu hóa cấu hình hẹn giờ dừng video trong JSON trả về từ `/youtubei/v1/player` và `/youtubei/v1/get_watch`.
  2. **Lớp 2 (MITM HTML & JS Injection + ServiceWorker Kill)**: Hủy ServiceWorker cache của YouTube và tiêm Watchdog vào cả HTML lẫn bundle JS.
  3. **Lớp 3 (Browser Extension MAIN World Content Script)**: Chạy trực tiếp trong ngữ cảnh trang YouTube ngay từ `document_start`, chặn đứng các sự kiện `visibilitychange`, `blur`, làm tươi `_lact` mỗi 5s và tự động phát lại tức thì nếu `<video>` bị dừng tự động.

---

## 3. Mối liên hệ
- Liên kết trực tiếp với [`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs) (Rust YouTube Extension).
- Liên kết với [`crates/proxify-core/src/storage.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/proxify-core/src/storage.rs) (Core Request Storage).
- Liên kết với [`backend/chrome_extension/manifest.json`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/manifest.json) và [`backend/chrome_extension/youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/youtube_anti_afk.js).

---

## 4. Rủi ro (Risks & Edge Cases)
- **Trường hợp người dùng chủ động bấm tạm dừng (Manual Pause)**: Nếu tự động gọi `video.play()` mù quáng, người dùng sẽ không thể bấm Pause video. Giải pháp đã triển khai biến trạng thái `userPaused` và `lastUserActionTs` chỉ ghi nhận sự kiện có `e.isTrusted === true` (click chuột hoặc bấm phím Space/`k`) trong vòng 800ms trước khi sự kiện `pause` nổ ra, giữ nguyên quyền tạm dừng thủ công của người dùng.
- **Kích thước gói JS (`desktop_polymer.js` / `base.js`)**: Khi không qua stream fast-path để chèn Watchdog, gói JS (~2-3MB) được giải nén và xử lý trong bộ nhớ; tuy nhiên trình duyệt sẽ cache lại bản đã tiêm hoặc nhận trực tiếp từ Content Script của Chrome Extension mà không gây trễ khung hình.
