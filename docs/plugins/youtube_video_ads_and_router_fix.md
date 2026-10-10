# Tài Liệu Kỹ Thuật: Khắc Phục Triệt Để Lỗi Lọt Video Ads YouTube & Sửa Định Tuyến Trie Router

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `backend/proxify/utils/youtube_utils.py`
  - Mở rộng danh mục từ khóa cấu hình quảng cáo `AD_CONFIG_KEYS` với 23 renderer/token quảng cáo video (pre-roll, mid-roll, in-player) hiện đại của YouTube:
    - Nhóm Video Ad Renderers: `instreamVideoAdRenderer`, `playerBytesAdLayoutRenderer`, `playerLegacyDesktopWatchAdsRenderer`, `inPlayerAdLayoutRenderer`, `playerAdParams`, `playerAdCard`.
    - Nhóm Placement & Config: `adPlacementRenderer`, `adPlacementConfig`, `clientForecastingAdRenderer`, `panelAdHeaderImageLockupViewModel`, `playerAdAvatarLockupCardButtonedViewModel`.
    - Nhóm Triggers & Telemetry: `slotEntryTrigger`, `slotExpirationTriggers`, `slotFulfillmentTriggers`, `slotIdEnteredTrigger`, `slotIdScheduledTrigger`, `triggeringSlotId`, `serializedSlotAdServingDataEntry`, `serializedAdServingDataEntry`.
    - Nhóm Giao diện Skip Ad: `skipAdButtonViewModel`, `skipAdViewModel`, `templatedAdText`, `visitAdvertiserLink`, `visitAdvertiserLinkViewModel`.
  - Trong `is_youtube_ad_request()`: Bổ sung endpoint ngắt quảng cáo giữa video `/youtubei/v1/get_midroll_info`.

- **File sửa đổi 2:** `backend/proxify/plugins/youtube.py`
  - Đổi tên miền mục tiêu từ chuỗi cụt `"youtubei"` thành FQDN `"youtubei.googleapis.com"`.
  - Nâng cấp cơ chế giải mã / nạp nội dung phản hồi trong `on_response()`: Sử dụng thuộc tính `flow.response.text` của mitmproxy thay vì `flow.response.content.decode('utf-8')`. Giúp tự động giải mã các luồng nén hiện đại (`gzip`, `deflate`, `br` - Brotli, `zstd`) và tự động cập nhật lại header `Content-Length`.

- **File sửa đổi 3:** `backend/proxify/server.py`
  - Sửa `_yt_mutator_domains`: Đăng ký `"youtubei.googleapis.com"` vào Radix Trie Router thay vì chuỗi cụt `"youtubei"`.

- **File sửa đổi 4:** `backend/tests/test_youtube_utils.py`
  - Bổ sung unit tests cho tất cả các token video ad renderer mới.
  - Bổ sung test case kiểm tra Trie Router ánh xạ chính xác `youtubei.googleapis.com`.
  - Toàn bộ test suite liên quan YouTube đạt tỷ lệ vượt qua 100% (3/3 passed).

- **Cấu hình Hệ thống (Windows):**
  - Kích hoạt lại `ProxyEnable = 1`.
  - Loại bỏ `*.google.com` và `*.googleapis.com` khỏi `ProxyOverride` trên Windows để ngăn Chrome bypass proxy đối với các máy chủ quảng cáo và API Innertube. Đồng bộ sang WinHTTP (`netsh winhttp import proxy source=ie`).

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng phản ánh: *"proxify không chặn quảng cáo - trên youtube, video ads"*. Mặc dù Proxify đã có plugin chặn quảng cáo YouTube từ trước, các video quảng cáo đầu video (pre-roll) và giữa video (mid-roll) vẫn hiển thị trên trình phát YouTube Web.

### Nguyên nhân gốc rễ (Root Cause)
1. **Thiếu bộ bóc tách các Video Ad Renderer thế hệ mới:**
   Phiên bản trước chỉ đổi tên `adPlacements`, nhưng bên trong mảng này chứa các đối tượng `adPlacementRenderer`, `instreamVideoAdRenderer`, `playerBytesAdLayoutRenderer`, `playerLegacyDesktopWatchAdsRenderer`. Trình phát YouTube Web (Player JS) khi không thấy `adPlacements` vẫn tiếp tục tìm thấy các layout renderer này và kích hoạt luồng phát video quảng cáo.
2. **Lỗi Radix Trie Router không khớp miền FQDN:**
   `ProxyRouter` duyệt domain theo từng phần đảo ngược (`com -> googleapis -> youtubei`). Do `server.py` chỉ đăng ký `"youtubei"` (top-level), việc tra cứu `youtubei.googleapis.com` trả về 0 Mutator. Mọi yêu cầu lấy thông tin player và quảng cáo gửi đến endpoint này đều bị bỏ lọt.
3. **Lỗ hổng cấu hình `ProxyEnable = 0` và `ProxyOverride`:**
   Windows Internet Settings từng bị tắt proxy (`ProxyEnable: 0`), kèm theo việc đặt `*.google.com` và `*.googleapis.com` vào danh sách bypass. Trình duyệt Chrome gửi thẳng các request quảng cáo ra ngoài Internet mà không qua Proxify.

### Ý nghĩa giải pháp
- **Triệt tiêu Video Ads từ cấu trúc dữ liệu:** Toàn bộ các đối tượng layout và renderer của video ad bị đổi tên thành `*_BLOCKED`, biến mọi payload phản hồi thành luồng video thuần túy như tài khoản YouTube Premium.
- **Hỗ trợ định dạng nén Brotli/Gzip chuẩn mực:** `flow.response.text` đảm bảo dữ liệu luôn được bóc tách chuẩn xác dù YouTube phản hồi bằng Brotli hay gzip.
- **Bảo toàn giao diện người dùng:** Kiểm tra hồi quy xác nhận không có bất kỳ xung đột nào với thanh điều hướng hoặc ô tìm kiếm (`ytd-masthead`).

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `backend/proxify/utils/youtube_utils.py` | Cung cấp hằng số `AD_CONFIG_KEYS` mở rộng và hàm khử quảng cáo `strip_youtube_ads` |
| `backend/proxify/plugins/youtube.py` | Plugin `YouTubePlugin` can thiệp luồng HTTP mitmproxy (chặn request ad 204, xử lý response text) |
| `backend/proxify/server.py` | Đăng ký FQDN `youtubei.googleapis.com` vào Trie Router ở chế độ Mutator |
| `backend/proxify/core/router.py` | Điều phối luồng request/response theo domain cây đảo ngược |
| Windows Registry / WinHTTP | Đảm bảo 100% traffic Chrome được chuyển tiếp về `127.0.0.1:8080` |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **YouTube cập nhật thêm tên Renderer mới trong tương lai:**
   - *Rủi ro:* YouTube có thể đổi tên `instreamVideoAdRenderer` thành một định danh khác.
   - *Biện pháp giảm thiểu:* Đã chặn đồng thời cả ở tầng mạng (drop HTTP 204 các endpoint `/api/stats/ads`, `/pagead/`, `doubleclick.net`, `adservice.google.com`, `/get_midroll_info`). Nếu video ad cố gắng gửi beacon hay load tracking, nó sẽ bị hủy ngay ở pha request.
2. **Server-Side Ad Insertion (SSAI):**
   - *Rủi ro:* Nếu YouTube ghép trực tiếp luồng quảng cáo vào cùng segment video `googlevideo.com` mà không khai báo qua JSON metadata.
   - *Đánh giá:* Trên nền tảng Desktop Web hiện tại, YouTube vẫn phân phối dựa trên client-side orchestration (`inPlayerAdLayoutRenderer`). Khi layout bị vô hiệu hóa, player tự động phát video chính từ timestamp 0.
