# Khắc phục Toàn diện Điểm Gãy Extension Bridge, Phục hồi Cơ chế Vượt Rào và Multi-Tenant

## Tóm tắt thay đổi
1. **`backend/chrome_extension/manifest.json`**:
   - Bổ sung quyền `"storage"` vào trường `"permissions"` trong Manifest V3.
   - Khắc phục lỗi `TypeError: Cannot read properties of undefined (reading 'local')` làm tê liệt popup extension khi người dùng bấm nút lấy cookie.
2. **`backend/chrome_extension/popup.js`**:
   - Thêm khối phòng vệ `try...catch` và kiểm tra `if (chrome.storage && chrome.storage.local)` khi đọc cấu hình `serverUrl` và `clientId`, tự động fallback về giá trị mặc định an toàn (`http://127.0.0.1:8888`, client `default`) nếu storage tạm thời không khả dụng.
3. **`backend/chrome_extension/background.js`**:
   - **Xóa bỏ hoàn toàn kiểm tra DOM sai lệch (False-Positive)**: Loại bỏ các đoạn check `bodyText.includes("Nội dung này hiện không khả dụng")` và `hasJoinButton` trên toàn tab, vốn chặn nhầm 100% request do các bài share bị xóa hoặc widget gợi ý nhóm trong feed.
   - **Bảo toàn cấu trúc Form-Data GraphQL**: Bỏ việc parse lại body bằng `URLSearchParams` (vốn gây hỏng chuỗi JSON encode của `variables` và phá vỡ chữ ký cryptographic Comet). Chuyển sang cơ chế bổ sung token LIVE (`fb_dtsg`, `jazoest`, `__user`, `lsd`) an toàn chỉ khi body còn thiếu hoặc rỗng.
4. **`backend/proxify/platforms/facebook/stealth.py`**:
   - Khôi phục `impersonate="chrome120"` trong `GlobalNetworkClient` để duy trì khả năng giả lập TLS ClientHello/JA3 Fingerprint của Google Chrome.
   - Sửa hàm `update_params` trong `SessionStateManager`: Duy trì và bảo toàn token phiên `__s` thật được capture từ trình duyệt của người dùng thay vì sinh mới chuỗi ngẫu nhiên trên từng request gây nghi ngờ chữ ký bot.
5. **`backend/proxify/platforms/facebook/crawler.py`**:
   - Truyền đầy đủ `client_id=self.client_id` vào tất cả các lời gọi `bridge.is_connected(...)` (dòng 262, 437, 1387, 1550) để đảm bảo hàng đợi công việc và nhịp tim được cô lập chính xác theo từng tenant.
   - Khi có lỗi ở request cào bình luận (`is_comment_crawl=True`), không gán cờ dừng khẩn cấp `self._stop_flag = True` trên feed crawler.
6. **`backend/tests/test_stealth.py` & `backend/tests/test_crawler_bridge_fixes.py`**:
   - Cập nhật và bổ sung bộ test kiểm tra quyền `storage`, kiểm tra cô lập `client_id` và kiểm tra an toàn cờ `_stop_flag`. Toàn bộ 45 unit tests đều vượt qua (100% PASSED).

## Mục đích & Ý nghĩa
- **Khôi phục hoạt động bình thường của toàn bộ hệ thống Proxify**: Giải quyết dứt điểm tình trạng Proxify không thể cào dữ liệu, không thể lấy cookie và bị dừng cào tức thì ngay từ trang đầu tiên.
- **Bảo tồn chữ ký mật mã (Cryptographic Integrity) của Facebook Comet**: Đảm bảo các gói tin GraphQL được thực thi trong Chrome tab không bị sai lệch cấu trúc URL-encoded và không bị Facebook từ chối với mã lỗi `1357001 (Invalid Token)` hay `1675004`.
- **Hoàn thiện tính năng Cô lập Đa Tenant (Multi-Tenant Bridge)**: Đảm bảo khi nhiều client cùng kết nối về server, mỗi client độc lập nhận đúng job của mình và kiểm tra trạng thái heartbeat tách biệt hoàn toàn.

## Mối liên hệ
- `backend/chrome_extension` $\leftrightarrow$ `backend/proxify/platforms/facebook/bridge.py`: Giao thức IPC hai chiều thông qua HTTP polling và script injection trong môi trường `world: "MAIN"`.
- `backend/proxify/platforms/facebook/crawler.py` $\leftrightarrow$ `backend/proxify/platforms/facebook/stealth.py`: Đồng bộ kiểm soát nhịp điệu cào tự nhiên (Gaussian distribution) và phiên làm việc.
- `backend/proxify/platforms/facebook/api.py` $\leftrightarrow$ `crawler.py`: Tiếp nhận request từ Web Dashboard, điều phối `client_id` tới đúng worker task.

## Rủi ro (Risks & Edge Cases)
1. **Người dùng cần tải lại Extension trong Chrome**:
   - Do có thay đổi trực tiếp trong file `manifest.json` và `background.js`, người dùng cần truy cập `chrome://extensions/` và bấm nút **🔄 Tải lại (Reload)** để Chrome nạp quyền `"storage"` mới.
2. **Tab Facebook cần được mở sẵn khi cào**:
   - Khi tiến hành cào nhóm hoặc cào bình luận, người dùng cần đảm bảo có ít nhất 1 tab `facebook.com` đang mở và đã đăng nhập trên trình duyệt để Extension Bridge có thể thực thi request ngầm trong tab đó.
