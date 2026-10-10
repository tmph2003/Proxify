# Tài Liệu Kỹ Thuật: Khắc Phục Lỗi Không Pause Được YouTube & Tái Thiết Kế Cơ Chế Clean Ad Pruning

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `backend/proxify/utils/youtube_utils.py`
  - **Loại bỏ 23 renderer/trigger/viewmodel tokens cấp lá khỏi `AD_CONFIG_KEYS`:**
    - Gỡ bỏ: `instreamVideoAdRenderer`, `playerBytesAdLayoutRenderer`, `playerLegacyDesktopWatchAdsRenderer`, `inPlayerAdLayoutRenderer`, `playerAdParams`, `adPlacementRenderer`, `adPlacementConfig`, `clientForecastingAdRenderer`, `playerAdCard`, `panelAdHeaderImageLockupViewModel`, `playerAdAvatarLockupCardButtonedViewModel`, `serializedSlotAdServingDataEntry`, `serializedAdServingDataEntry`, `slotEntryTrigger`, `slotExpirationTriggers`, `slotFulfillmentTriggers`, `slotIdEnteredTrigger`, `slotIdScheduledTrigger`, `triggeringSlotId`, `skipAdButtonViewModel`, `skipAdViewModel`, `templatedAdText`, `visitAdvertiserLink`, `visitAdvertiserLinkViewModel`.
    - Giữ lại thuần túy các **container tokens cấp gốc**: `adPlacements`, `adSlots`, `playerAds`, `adBreakHeartbeatParams`, `adSlotRenderer`, `inFeedAdLayoutRenderer`, `promotedVideoRenderer`, `promotedSparklesWebRenderer`, `compactPromotedVideoRenderer`, `statementBannerRenderer`, `primetimeMastheadRenderer`, `adsEngagementPanelContentRenderer`.
  - **Triển khai hàm `clean_youtube_json_data(obj)`:**
    - Parse JSON chuẩn mực đối với các phản hồi Innertube API (`/youtubei/v1/player`, `/youtubei/v1/get_watch`, `/youtubei/v1/browse`).
    - Xóa bỏ triệt để (prune / `del`) các đối tượng gốc `adPlacements`, `adSlots`, `playerAds`, `adBreakHeartbeatParams` khỏi `playerResponse` thay vì đổi tên thành `*_BLOCKED`.
    - Lọc bỏ panel quảng cáo trong `watchNextResponse.engagementPanels` (`targetId == "engagement-panel-ads"`).
    - Loại bỏ trực tiếp các thẻ card quảng cáo feed (`adSlotRenderer`, `inFeedAdLayoutRenderer`) khỏi mảng `contents` để tránh sinh placeholder trống.
  - **Cải tiến `strip_youtube_ads(body)`:**
    - Phân tách 2 luồng: Innertube JSON API (parse và prune sạch cấu trúc AST) và HTML watch/home page (chỉ can thiệp biến inline `ytInitialPlayerResponse`).
    - Tuyệt đối không can thiệp hay đổi tên các class trong `preloadMessageNames` của Polymer SPA trên HTML gốc (`GET /`).
  - **Cập nhật `is_youtube_ad_request(url, domain)`:**
    - Thêm endpoint ngắt quảng cáo midroll chuẩn: `/get_midroll_info`.
    - Loại bỏ chặn mặc định `/ptracking`: Vì `/ptracking?pltype=content` là ping theo dõi phát lại hợp lệ của video chính, việc drop bừa bãi gây lỗi đồng bộ client.

- **File sửa đổi 2:** `backend/proxify/plugins/youtube.py`
  - Trong `on_response()`: Bỏ kiểm tra `/api/stats` trong `is_api` vì endpoint này trả về 204 No Content và không chứa nội dung video/quảng cáo.

- **File sửa đổi 3:** `backend/tests/test_youtube_utils.py`
  - Cập nhật test cases kiểm tra tính hợp lệ của việc clean pruning JSON AST đối với `playerResponse` và `watchNextResponse`.
  - Bổ sung test case bảo toàn request tracking hợp lệ `/ptracking?pltype=content`.
  - Toàn bộ test suite 60/60 tests passed 100%.

- **Vận hành hệ thống:**
  - Khởi động lại container Docker `proxify_app` để cập nhật mã nguồn mới nhất.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Phản hồi người dùng
Người dùng phản ánh: *"check proxify đi, giờ tôi còn không pause được youtube nữa cơ"*.
Trình phát YouTube vẫn phát video chính bình thường (âm thanh/hình ảnh vẫn chạy), nhưng:
- Nhấn phím `Spacebar` hoặc phím `k` không thể tạm dừng video.
- Nhấp chuột trực tiếp vào màn hình video player không có tác dụng.
- Nút Play/Pause ở góc trái thanh điều khiển (`.ytp-play-button`) bị vô hiệu hoặc liên tục kích hoạt lại `playVideo()`.

### Nguyên nhân gốc rễ (Root Cause Analysis - RCA)
1. **Mô hình "Frankenstein" AST làm sụp đổ State Machine của YouTube Player:**
   - Phiên bản trước thực hiện thay thế chuỗi thô (`replace`) hàng loạt token nội bộ (`instreamVideoAdRenderer`, `slotExpirationTriggers`, `skipAdViewModel`).
   - Hậu quả: Đối tượng cha `playerOverlayLayoutRenderer` vẫn tồn tại, khiến YouTube Player render một lớp phủ overlay trong suốt (`100% width, 100% height`) đè lên thẻ `<video>`.
   - Khi logic JavaScript của YouTube (`base.js`) chạy để tính toán nút Skip Ad hoặc trigger hết hạn slot (`slotExpirationTriggers`), các thuộc tính con đã bị đổi tên thành `*_BLOCKED` -> dẫn đến `TypeError: Cannot read properties of undefined`.
   - Ngoại lệ chưa xử lý khiến Ad Slot **không bao giờ expire**. Lớp phủ overlay quảng cáo tồn tại vĩnh viễn trên bề mặt video, nuốt trọn toàn bộ thao tác click chuột của người dùng.
2. **Kẹt trạng thái `getPresentingPlayerType() === 2` (AD Mode):**
   - Trong `base.js`, hàm `pauseVideo()` kiểm tra `var y = this.app.getPresentingPlayerType()`. Nếu `y === 2` (Player đang nghĩ là đang chiếu Ad), YouTube theo thiết kế cố tình **bỏ qua / vô hiệu hóa lệnh pause** từ phím tắt (`Space`, `k`) để ngăn người dùng pause quảng cáo bắt buộc.
3. **Phá vỡ Module Loader trên trang chủ (`GET /`):**
   - Chuỗi thô thay thế `adSlotRenderer` thành `adSlotRenderer_BLOCKED` bên trong `webResponseContextPreloadData.preloadMessageNames`. Module loader của YouTube không thể tìm thấy message type này, làm gián đoạn việc đăng ký event listeners của toàn bộ ứng dụng web.

### Ý nghĩa giải pháp (Clean Architecture & Industry Best Practice)
- **Học tập tiêu chuẩn uBlock Origin / Brave:** Thay vì can thiệp vào các nhánh con, chỉ cần loại bỏ sạch sẽ 4 container gốc (`adPlacements`, `adSlots`, `playerAds`, `adBreakHeartbeatParams`) khỏi `playerResponse`.
- **Đạt trạng thái Clean Video (tương đương YouTube Premium):**
  Trong `base.js`, hàm kiểm tra quảng cáo `ygQ` đánh giá:
  `if (!u || (!u.adPlacements && !u.adSlots)) return false;`
  Khi không có container quảng cáo, YouTube Player khẳng định video 100% không có quảng cáo:
  - Không khởi tạo Ad Slot Engine.
  - Không chèn bất kỳ lớp phủ Overlay nào.
  - `getPresentingPlayerType()` trả về `1` (Main Content Video).
  - Khôi phục hoàn toàn tính năng Play/Pause qua phím cách, phím `k` và click chuột trực tiếp.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `backend/proxify/utils/youtube_utils.py` | Cung cấp hàm `clean_youtube_json_data` (pruning JSON AST) và `strip_youtube_ads` (làm sạch response) |
| `backend/proxify/plugins/youtube.py` | Plugin `YouTubePlugin` can thiệp luồng HTTP, áp dụng bộ bóc tách JSON/HTML và drop các endpoint ads |
| `backend/proxify/server.py` | Radix Trie Router điều phối lưu lượng domain `youtube.com` và `youtubei.googleapis.com` vào Mutator |
| Trình duyệt Chrome / YouTube Web Client | Nhận payload sạch chuẩn JSON, khởi tạo Player State Machine ở chế độ phát nội dung thuần túy |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Payload JSON bị cắt cụt (Truncated Chunk) do streaming:**
   - *Rủi ro:* Nếu phản hồi Innertube quá dài và bị phân mảnh, `json.loads()` có thể ném ngoại lệ `JSONDecodeError`.
   - *Biện pháp giảm thiểu:* Đã bọc khối `try...except`, tự động fallback sang cơ chế thay thế container an toàn mà không làm sập tiến trình proxy hay trả về response rỗng cho client.
2. **YouTube cập nhật cấu hình phản hồi Watch Next dạng Protocol Buffers nhị phân:**
   - *Đánh giá:* Trên Desktop Web, Innertube API hiện tại luôn phản hồi JSON UTF-8. Cơ chế parse đệ quy `clean_youtube_json_data` tự thích ứng với các độ sâu lồng nhau khác nhau của `playerResponse`.
