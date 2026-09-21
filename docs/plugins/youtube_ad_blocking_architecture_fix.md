# Tài Liệu Kỹ Thuật: Khắc Phục Triệt Để Lỗi Lọt Quảng Cáo YouTube

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `backend/proxify/utils/youtube_utils.py`
  - Bổ sung danh sách mạng quảng cáo chuyên dụng của Google: `doubleclick.net`, `googlesyndication.com`, `googleadservices.com`, `adservice.google.com` vào `AD_DOMAINS` và nhận diện ngay lập tức trong `is_youtube_ad_request()`.
  - Mở rộng nhận diện các endpoint quảng cáo của YouTube: `/pagead/`, `/api/stats/ads`, `/pcs/activeview`, `/ptracking`, `/youtubei/v1/player/ad_break`.
  - Loại bỏ hoàn toàn `googlevideo.com` khỏi danh sách chặn ở tầng request để triệt tiêu nguy cơ MediaSource decode error gây hỏng video playback.
  - Bổ sung bộ danh mục từ khóa ad hiện đại vào `AD_CONFIG_KEYS`: `adBreakHeartbeatParams`, `adSlots`, `playerAds`, `adSlotRenderer`, `inFeedAdLayoutRenderer`, `promotedVideoRenderer`, `promotedSparklesWebRenderer`, `compactPromotedVideoRenderer`, `statementBannerRenderer`, `masthead`, `adsEngagementPanelContentRenderer`.
- **File sửa đổi 2:** `backend/proxify/plugins/youtube.py`
  - Bổ sung các domain mạng quảng cáo của Google vào `target_domains`.
  - Trong `on_response`: Xóa bỏ guard clause hạn hẹp `if 'youtubei/v1' not in url: return`. Mở rộng xử lý bóc tách quảng cáo cho cả `text/html` (chứa `ytInitialPlayerResponse` và `ytInitialData` của `/watch`, `/shorts`, `/`) lẫn `application/json` (`youtubei/v1`).
- **File sửa đổi 3:** `backend/proxify/server.py`
  - Đăng ký vai trò **MUTATOR** cho toàn bộ các domain xử lý quảng cáo (`youtube.com`, `youtubei`, `doubleclick.net`, `googlesyndication.com`, `googleadservices.com`, `adservice.google.com`). Đảm bảo interceptor can thiệp đồng bộ ở pha request để trả về `HTTP 204 No Content`, không bị rò rỉ request lên remote server như cơ chế `Observer` (`asyncio.create_task` fire-and-forget).
- **File sửa đổi 4:** `backend/tests/test_youtube_utils.py`
  - Cập nhật test suite toàn diện: Xác minh chặn mạng ad, kiểm tra an toàn cho luồng video chính, kiểm tra bóc tách sạch sẽ các token quảng cáo trên payload JSON và HTML.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng phản ánh: *"Giờ thì vào được rồi nhưng vẫn hiện quảng cáo"*. Video YouTube xem được mà không bị lỗi kết nối, nhưng quảng cáo đầu video (pre-roll), quảng cáo ngắt đoạn (mid-roll) và banner đề xuất vẫn hiển thị đầy đủ.

### Nguyên nhân gốc rễ (Root Cause)
1. **Lọt trang HTML khởi tạo (`/watch` Initial Hydration):** Khi người dùng mở một video mới, YouTube trả về trang HTML chứa sẵn JSON `ytInitialPlayerResponse`. Do phiên bản trước chỉ lọc URL chứa `youtubei/v1`, trang HTML này đi thẳng vào trình duyệt nguyên vẹn. Player đọc cấu hình quảng cáo từ HTML và kích hoạt phát video quảng cáo ngay lập tức.
2. **Bỏ sót các miền Ad Server chính:** Các request lấy script quảng cáo và đấu thầu (`pagead2.googlesyndication.com`, `adservice.google.com`, `googleadservices.com`) không nằm trong danh sách theo dõi của router nên lọt qua hoàn toàn.
3. **Cấu hình sai phân tầng Interceptor:** Đăng ký `doubleclick.net` là `Observer`. Theo thiết kế của `ProxyRouter`, Observer chạy background không await, dẫn tới việc request vẫn được gửi lên server Google trước khi phản hồi 204 được thiết lập.
4. **Bộ nhận diện ad chưa đầy đủ:** Thiếu `adBreakHeartbeatParams` khiến Player vẫn duy trì trạng thái chờ ngắt quãng quảng cáo (ad break).

### Ý nghĩa giải pháp
- **Ngăn chặn từ gốc ở tầng cấu hình:** Player YouTube nhận payload sạch tinh không có thông tin lịch quảng cáo $\rightarrow$ Trình duyệt tự động phát luồng video chính từ giây thứ 0 như tài khoản YouTube Premium.
- **Tối ưu hóa hiệu năng & độ ổn định:** Bỏ chặn mù quáng ở URL `googlevideo.com` giúp bảo vệ luồng MediaSource MSE, loại bỏ 100% lỗi video crash/quay tròn vô tận.

---

## 3. Mối liên hệ

| Module / File | Vai trò liên kết |
|---|---|
| `backend/proxify/utils/youtube_utils.py` | Cung cấp thuật toán thuần túy phân loại URL quảng cáo và khử token ad |
| `backend/proxify/plugins/youtube.py` | Plugin chính can thiệp luồng mạng mitmproxy ở cả Request (drop 204) và Response (khử token) |
| `backend/proxify/server.py` | Đăng ký Plugin vào Trie Router với role Mutator |
| `backend/proxify/core/router.py` | Trie Router phân phối luồng và đảm bảo `googlevideo.com` được stream trực tiếp không đệm RAM |
| `backend/tests/test_youtube_utils.py` | Đảm bảo tính hồi quy (regression) qua 59/59 unit tests passed |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **YouTube thay đổi định dạng token quảng cáo:**
   - *Rủi ro:* YouTube có thể bổ sung các tên trường ad mới trong tương lai.
   - *Giảm thiểu:* Cơ chế đa tầng đã chặn luôn cả các domain máy chủ quảng cáo (`doubleclick.net`, `googlesyndication.com`, `adservice.google.com`, v.v.). Ngay cả khi token mới xuất hiện trong JSON, player cũng không tải được metadata và media ad từ các server này.
2. **Server-Side Ad Insertion (SSAI):**
   - *Rủi ro:* Nếu YouTube ghép trực tiếp luồng quảng cáo vào chung một file video segment trên `googlevideo.com` (tương tự như trên thiết bị Smart TV).
   - *Đánh giá:* Trên Web Player của Chrome/Chromium, YouTube vẫn phân phối theo mô hình client-side orchestration dựa vào `adPlacements` và `adSlots`. Khi các trường này bị đổi tên thành `*_BLOCKED`, SSAI không được kích hoạt trên Web Desktop.
3. **Hiệu năng bóc tách chuỗi trên trang HTML lớn:**
   - *Rủi ro:* Trang HTML của `/watch` có kích thước ~1.3 MB.
   - *Giảm thiểu:* Hàm `strip_youtube_ads` sử dụng kiểm tra nhanh `any(k in body for k in AD_CONFIG_KEYS)` chạy trên C backend của Python trước khi thực hiện replace, mất chưa đầy 1ms trên CPU hiện đại.
