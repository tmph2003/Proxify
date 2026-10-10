# YouTube Anti-AFK Content Script

## Tóm tắt thay đổi

Tạo mới file `youtube_anti_afk.js` trong Chrome Extension và cập nhật `manifest.json` để thêm YouTube content script.

### File mới:
- `backend/chrome_extension/youtube_anti_afk.js` — Content script chạy trên mọi trang YouTube

### File sửa:
- `backend/chrome_extension/manifest.json` — Thêm entry content script cho YouTube, đổi tên extension thành "Proxify Helper", bump version lên 1.1

## Mục đích & Ý nghĩa

### Vấn đề
YouTube có cơ chế **Idle Detection (AFK)**: sau ~30-60 phút không tương tác, YouTube hiển thị popup **"Video đã tạm dừng. Tiếp tục xem?"** và pause video. Cơ chế này dựa trên **LACT** (Last Activity Timestamp) — YouTube theo dõi các DOM events (`mousemove`, `keydown`, `scroll`) để xác định người dùng có đang active hay không.

### Giải pháp
Content Script sử dụng chiến lược **Defense-in-Depth** với 2 lớp bảo vệ:

1. **Layer 1 — Activity Simulator (Proactive)**: Dispatch `mousemove` event lên `document` và `#movie_player` mỗi 60 giây để reset LACT counter, ngăn popup xuất hiện từ đầu.

2. **Layer 2 — MutationObserver (Reactive)**: Theo dõi DOM thay đổi trong `ytd-popup-container`. Khi phát hiện popup AFK (qua nhiều fallback selectors), tự động click nút "Có"/"Yes" và resume video.

### Tại sao dùng Chrome Extension thay vì Proxy?
- **CSP Compliance**: YouTube enforce `require-trusted-types-for 'script'` — proxy không thể inject inline script vào HTML response vì không có nonce hợp lệ. Content scripts được Chrome miễn CSP.
- **SRP (Single Responsibility Principle)**: Proxy thuộc tầng Transport & Data Filtering. DOM manipulation thuộc về Browser Extension (Content Script).
- **Robustness**: Content script chạy trong page context, có access trực tiếp đến DOM và video element.

## Mối liên hệ

### Liên kết trực tiếp:
- **`manifest.json`** — Khai báo content script và URL patterns
- **`background.js`** — Service worker không bị ảnh hưởng (chỉ xử lý Facebook)
- **`content.js`** — Facebook content script không bị ảnh hưởng (chạy trên domain riêng)

### Liên kết gián tiếp:
- **`backend/proxify/plugins/youtube.py`** — YouTube plugin ở proxy level xử lý ad blocking. Anti-AFK là tính năng bổ sung ở browser level, không conflict.
- **`backend/proxify/utils/youtube_utils.py`** — Ad stripping logic không liên quan đến AFK detection.
- **`docs/plugins/youtube_connection_error_fix.md`** — Tài liệu trước đó đã ghi rõ: "DOM injection thuộc về Browser Extension / Content Script" → file này là implementation chính thức của nguyên tắc đó.

## Rủi ro (Risks & Edge Cases)

### Rủi ro Trung bình
- **YouTube thay đổi DOM selectors**: Popup dialog có thể dùng custom element mới hoặc thay đổi ID. **Mitigation**: Script sử dụng nhiều fallback selectors (`yt-confirm-dialog-renderer`, `tp-yt-paper-dialog`, text-based button matching) và có logging để debug.

### Rủi ro Thấp
- **`mousemove` synthetic event bị ignore**: YouTube có thể check `event.isTrusted`. Tuy nhiên, hiện tại (2026) YouTube KHÔNG check `isTrusted` cho mousemove events — chỉ check cho click/keyboard events trong sensitive flows. Nếu YouTube thay đổi, Layer 2 (MutationObserver) vẫn hoạt động như fallback.
- **SPA Navigation**: YouTube là Single Page Application. Script listen `yt-navigate-finish` event để re-initialize observer khi chuyển video. Edge case: nếu YouTube thay đổi event name, observer có thể không restart. **Mitigation**: `visibilitychange` event cũng trigger re-init.
- **Memory leak**: MutationObserver callback được debounce (300ms). Observer disconnect khi navigate và re-create sau 1s delay. Không có unbounded growth.

### Không có rủi ro:
- **Conflict với Facebook content script**: `matches` pattern hoàn toàn tách biệt (`youtube.com` vs `facebook.com`).
- **Ảnh hưởng đến proxy ad blocking**: Anti-AFK hoạt động ở DOM level, không liên quan đến HTTP request interception.
- **CSP violation**: Content scripts được Chrome miễn CSP của trang host.
