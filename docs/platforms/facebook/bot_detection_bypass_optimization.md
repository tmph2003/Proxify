# Tối ưu hóa Toàn diện Cơ chế Bypass Bot Detection Facebook (Unblockable Stealth)

## Tóm tắt thay đổi
1. **`backend/chrome_extension/background.js`**:
   - Bắt buộc ghi đè (Override) vô điều kiện các token LIVE (`fb_dtsg`, `jazoest`, `__user`, `av`, `lsd`) lấy trực tiếp từ `DTSGInitialData` và `CurrentUserInitialData` vào `body` của request GraphQL thay vì chỉ thêm khi thiếu.
   - Trích xuất và cập nhật đồng bộ các tham số `SiteData` (`__hs`, `__rev`, `__hsi`, `__spin_r`, `__spin_b`, `__spin_t`) từ tab đang mở.
   - Loại bỏ hoàn toàn cơ chế Fallback gửi request từ Service Worker của Extension để tránh rò rỉ header `Origin: chrome-extension://...` hoặc context không hợp lệ.
2. **`backend/proxify/platforms/facebook/crawler.py`**:
   - Xóa bỏ 100% các nhánh fallback gửi request trực tiếp bằng `curl_cffi` từ Docker khi cào bài viết/comment (`_safe_request`). Nếu Extension ngắt kết nối, dừng cào an toàn để bảo vệ tài khoản người dùng thay vì gửi request từ IP Docker.
   - Chuyển cơ chế cào HTML fallback của comment (`_crawl_comments_html_fallback`) sang định tuyến qua Extension Bridge (`_safe_request`).
   - Tích hợp `self._comment_session_state.update_params(data)` vào `_fetch_comments` và `_fetch_replies` để tự động biến thiên Base36 counter `__req`, `__s`, và timestamp `__spin_t` trên từng request bình luận.
   - Chuẩn hóa User-Agent lấy từ `IN_MEMORY_COOKIES.get("user_agent")`, loại bỏ hoàn toàn các phiên bản hardcode viễn tưởng `Chrome/152.0.0.0` và `Chrome/120.0.0.0`.
3. **`backend/proxify/platforms/facebook/stealth.py`**:
   - Nâng cấp `CrawlDelayConfig` cho comment lên ngưỡng hành vi con người tự nhiên (`comment_min: 1.5s`, `comment_mean: 2.5s`, `comment_max: 5.0s`, kèm 5% xác suất nghỉ đọc lâu 3-7s).
   - Cập nhật `SessionStateManager.update_params` để luôn làm mới `__s` ngẫu nhiên và `__spin_t` trên mọi request.
   - Bỏ gán cứng `impersonate="chrome120"` trong `GlobalNetworkClient`.
4. **`backend/proxify/platforms/facebook/api.py`**:
   - Chuyển tác vụ kiểm tra trạng thái bài viết (`check_status`) qua `bridge.execute_request` trong tab Chrome thật thay vì dùng `StealthSessionManager` gửi từ Docker IP.
   - Chuẩn hóa fallback User-Agent, loại bỏ `Chrome/152.0.0.0`.
5. **`backend/proxify/platforms/facebook/auth.py`**:
   - Chuẩn hóa fallback User-Agent thành Chrome hiện đại.
6. **`backend/tests/test_stealth.py`**:
   - Bổ sung unit tests cho `TestFacebookStealth` kiểm tra `SessionStateManager` mutation và `CrawlDelayConfig` constraints.

## Mục đích & Ý nghĩa
- **Triệt tiêu nguy cơ Session Hijacking / Checkpoint / Logout tài khoản**: Facebook kiểm soát rất chặt chẽ mối liên hệ giữa session (`c_user`, `xs`) với IP và ngữ cảnh TLS trình duyệt. Bất kỳ request nào xuất phát từ container Docker đều là nguồn gốc khiến người dùng bị ép logout. Việc ép 100% request có session phải đi qua Chrome tab thật loại bỏ hoàn toàn dấu hiệu bất thường này.
- **Xóa bỏ dứt điểm mã lỗi Facebook 1357001 (Invalid DTSG Token)**: Trước đây, `background.js` chỉ inject `liveDtsg` nếu body chưa có `fb_dtsg=`. Vì template luôn có token cũ nên token LIVE không bao giờ được ghi đè, dẫn đến lỗi auth 1357001 và buộc hệ thống phải cào DOM chắp vá.
- **Loại bỏ chữ ký bot máy móc trong phân trang bình luận**: Việc gửi liên tiếp hàng chục request GraphQL cào comment với cùng một giá trị `__req`, `__s` tĩnh và tốc độ siêu nhanh (300ms) là chữ ký bot kinh điển. Cải tiến mới giúp nhịp điệu cào comment biến thiên theo phân phối chuẩn Gaussian thực tế và cập nhật đơn điệu Base36 `__req`.
- **Nhất quán Fingerprint (Zero Mismatch)**: Không còn hiện tượng TLS giả lập Chrome 120 nhưng User-Agent khai báo Chrome 152 hay Chrome 127.

## Mối liên hệ
- `backend/chrome_extension/background.js` $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py`: Đảm bảo giao tiếp an toàn, trong sáng, chỉ thực thi trong ngữ cảnh `world: "MAIN"` của tab Facebook thật.
- `backend/proxify/platforms/facebook/crawler.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/stealth.py`: Đồng bộ trạng thái phiên động và phân phối độ trễ hành vi con người.
- `backend/proxify/platforms/facebook/api.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py`: Chuyển đổi toàn bộ các endpoint kiểm tra trạng thái bài viết về môi trường trình duyệt thật.

## Rủi ro (Risks & Edge Cases)
1. **Yêu cầu bắt buộc phải mở Tab Facebook và bật Extension**:
   - Vì đã triệt tiêu hoàn toàn các fallback direct request nguy hiểm từ Docker, nếu người dùng tắt trình duyệt Chrome hoặc đóng tab Facebook, crawler sẽ dừng an toàn và thông báo lỗi kết nối. Người dùng chỉ cần mở tab Facebook và bấm tiếp tục.
2. **Cần Reload Extension trong Chrome**:
   - Do có thay đổi trong `backend/chrome_extension/background.js`, người dùng cần truy cập `chrome://extensions/` và nhấn nút **🔄 Tải lại (Reload)** trên Extension Proxify để cập nhật code mới.
