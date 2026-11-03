# YouTube SABR Ad Fast-Forward, Playlist Auto-Skip Fix & Rust Hot-Path Optimization (v8.4)

> [!IMPORTANT]
> Ngày cập nhật: 2026-11-03. Phiên bản: v8.4 (Vô hiệu hóa chặn mạng HTTP 204 cho SABR + Vô hiệu hóa script `youtube_anti_afk.js` cũ trong Chrome Extension + Khóa bảo vệ `curDocId === mainVid`).

## Tóm tắt thay đổi

1. **Vô hiệu hóa hoàn toàn việc trả về HTTP `204 No Content` trong `is_youtube_ad_request()` ([`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs))**:
   - Qua kiểm tra log lúc `02:07:40Z`–`02:07:49Z`:
     - `02:07:40.416Z`: Nạp `/watch?v=yphv1bemdfg&list=rdmm-5mwcpgrtqk&index=4`
     - `02:07:41.891Z`: `Blocked: GET https://www.google.com/pagead/lvz?evtid=...` (HTTP `204`)
     - `02:07:48.582Z` (chỉ 6.7 giây sau): Trình phát tự động nhảy sang `index=5` (`/watch?v=vqvaizid7yy&list=rdmm-5mwcpgrtqk&index=5`)!
   - **Nguyên nhân cốt lõi:** Khi `ytInitialPlayerResponse` hoặc `/youtubei/v1/player` chứa `adPlacements`/`adSlots`, trình phát SABR của YouTube gửi request xác thực quảng cáo tới `www.google.com/pagead/lvz` và `doubleclick.net`. Khi Proxy chặn các request này bằng HTTP `204 No Content`, SABR lập tức kích hoạt `onAbnormalityDetected` (mã lỗi `282054944`) và tự động chuyển sang bài kế tiếp trong Playlist sau ~6–7 giây.
   - **Giải pháp:** Đặt `is_youtube_ad_request()` luôn trả về `false` (giống kiến trúc ổn định ở v7), để toàn bộ quá trình tua nhanh quảng cáo (`video.currentTime = video.duration` khi `curDocId !== mainVid`) và ẩn lớp phủ CSS (`#proxify-yt-ad-style`) được thực thi 100% an toàn ở phía Client bởi `YOUTUBE_WATCHDOG_JS`.

2. **Vô hiệu hóa triệt để `youtube_anti_afk.js` v1.5 cũ của Chrome Extension ([`private/chrome_extension_fb/youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/private/chrome_extension_fb/youtube_anti_afk.js) & [`backend/chrome_extension/youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/youtube_anti_afk.js))**:
   - Nếu trình duyệt Chrome chưa được bấm nút **Reload** trong `chrome://extensions` kể từ khi nâng cấp manifest v1.6, Chrome vẫn tiêm tệp `youtube_anti_afk.js` v1.5 từ ổ đĩa vào tab YouTube.
   - Tệp `youtube_anti_afk.js` v1.5 cũ chạy vòng lặp 200ms gọi `video.currentTime = video.duration` vô điều kiện, `player.skipAd()`, và `.ytp-skip-ad-button.click()`.
   - **Giải pháp kép:**
     1. Trong `YOUTUBE_WATCHDOG_JS` (chạy ngay đầu thẻ `<head>`), đặt cờ `window.__proxify_ext_anti_afk_v15__ = true;` để chặn đứng hàm khởi tạo của script extension cũ nếu nó vẫn còn trong bộ nhớ Chrome.
     2. Thay thế nội dung hai tệp `private/chrome_extension_fb/youtube_anti_afk.js` và `backend/chrome_extension/youtube_anti_afk.js` trên ổ đĩa bằng no-op stub an toàn.

3. **Khóa bảo vệ định danh Video (`curDocId === mainVid`) trong `YOUTUBE_WATCHDOG_JS` ([`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs))**:
   - Kiểm tra `player.getVideoStats().docid` (`curDocId`) so với tham số `v` trên URL (`mainVid`). Nếu `curDocId === mainVid` (tức `<video>` đang phát bài hát chính hoặc luồng Live chính), Watchdog tuyệt đối không tua `video.currentTime` và không bật `playbackRate = 16.0`.

4. **Tối ưu hóa hiệu năng Rust trên Hot Path ([`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs) & [`crates/proxify-core/src/router.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/proxify-core/src/router.rs))**:
   - Fast pre-check `text.contains("youThere") || text.contains("lactThresholdMs")` trước khi parse JSON trên `/player`, `/get_watch`, `/next`, `/browse`.
   - Thay `replacen` bằng `replace_range` trong `strip_youtube_ads()`.
   - Gộp 3 lần giữ khóa `RwLock` trong `ProxyRouter::should_stream_request()` thành 1 lần duy nhất.

## Mục đích & Ý nghĩa

Đảm bảo YouTube Playlist (`list=RDMM...`) phát trọn vẹn từng bài hát mà không bao giờ bị lỗi SABR `282054944` hay bị script cũ tua nhầm bài hát chính, đồng thời vẫn tự động tua qua quảng cáo instream trong tích tắc và ẩn sạch quảng cáo banner/chia màn hình trên Live Stream.

## Mối liên hệ

- **[`crates/ext-youtube/src/lib.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/crates/ext-youtube/src/lib.rs)**: Cập nhật `YOUTUBE_WATCHDOG_JS`, `is_youtube_ad_request()`, và unit tests.
- **[`private/chrome_extension_fb/youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/private/chrome_extension_fb/youtube_anti_afk.js)** & **[`backend/chrome_extension/youtube_anti_afk.js`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/chrome_extension/youtube_anti_afk.js)**: Chuyển thành no-op stub.
- **[`tests/e2e_extension_tests.rs`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/tests/e2e_extension_tests.rs)**: Cập nhật kiểm thử tương thích SABR.

## Rủi ro (Risks & Edge Cases)

- **Tab YouTube đã mở từ trước:** Vì YouTube là ứng dụng SPA (chuyển bài bằng lịch sử trình duyệt mà không tải lại HTML), nếu tab YouTube chưa được tải lại (`F5` / `Ctrl + F5`) sau khi container khởi động xong, biến `setInterval` của bản script cũ trong RAM của tab đó vẫn tiếp tục chạy. Người dùng cần nhấn `Ctrl + F5` một lần trên tab YouTube để nạp HTML mới có gắn cờ `window.__proxify_ext_anti_afk_v15__ = true`.
