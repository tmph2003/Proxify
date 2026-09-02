# Extension Bridge Architecture (Anti-Detect Browser Bypass)

## Tóm tắt thay đổi
Hệ thống Proxify Crawler đã được nâng cấp bằng kiến trúc **Extension Bridge**. 
Thay vì sử dụng Python (`curl_cffi`) để trực tiếp gửi các truy vấn GraphQL lên Facebook, hệ thống Backend giờ đây sẽ đóng gói các tham số của truy vấn (URL, Payload) và đẩy vào một hàng đợi (Queue). Chrome Extension (`background.js`) sẽ liên tục gọi API `GET /api/facebook/bridge/jobs` (Long-polling) để nhận nhiệm vụ, sử dụng hàm `fetch()` nguyên bản của trình duyệt để gọi lên Facebook, và gửi kết quả về lại Backend qua API `POST /api/facebook/bridge/result`.

## Mục đích & Ý nghĩa
Sự thay đổi này được sinh ra nhằm mục đích giải quyết triệt để lỗi **1357001 (Đăng nhập để tiếp tục)** gây ra bởi hệ thống bảo mật chống trộm Cookie của Facebook kết hợp với trình duyệt ẩn danh (CloakBrowser). 
- **Tại sao cần nó?** Trình duyệt ẩn danh của người dùng đã tự động che giấu Cookie `xs` khỏi mọi hàm Javascript và API Extension (`chrome.cookies`, `webRequest`), đồng thời sử dụng một mã hóa TLS Fingerprint độc quyền. Bất kỳ request nào gửi từ Python (dù đã đồng bộ HTTP Headers) đều không khớp TLS Fingerprint hoặc thiếu `xs`, dẫn đến việc Facebook lập tức thu hồi phiên đăng nhập. Việc đẩy request lên cho trình duyệt thật chạy bằng `fetch()` giúp qua mặt 100% các thuật toán phát hiện bất thường này, vì request phát ra mang đầy đủ TLS và Cookie ẩn.

## Mối liên hệ
- **`backend/proxify/platforms/facebook/bridge.py`**: Chứa class `ExtensionBridge` quản lý hàng đợi Jobs và luồng sự kiện (asyncio.Event) chờ kết quả.
- **`backend/proxify/platforms/facebook/api.py`**: Cung cấp hai API nội bộ cho Extension giao tiếp (`/bridge/jobs` và `/bridge/result`).
- **`backend/proxify/platforms/facebook/crawler.py`**: Đã thay thế hàm `_safe_request()` (trước đây gọi qua `StealthSessionManager`) để đẩy request vào Bridge.
- **`backend/chrome_extension/background.js`**: Thêm luồng `pollForBridgeJobs()` chạy vòng lặp bất tận để nhận lệnh và thực thi `fetch()`.

## Rủi ro (Risks & Edge Cases)
1. **Rủi ro quá tải trình duyệt:** Vì các request crawl hiện tại được thực thi trên background script của Extension, một số lượng quá lớn các request liên tục có thể gây chậm trình duyệt của người dùng.
2. **Tab Sleeping/Inactive:** Nếu trình duyệt đưa Extension vào trạng thái ngủ ngắt quãng (Service Worker inactive), tiến trình crawl có thể bị Timeout (mặc định 30 giây).
3. **Giới hạn kết nối (CORS):** Nếu Facebook thiết lập chính sách CORS chặt chẽ ngăn cản Extension gọi lệnh `fetch()` mà không có đủ Headers (tuy nhiên `fetch` từ extension có quyền `host_permissions` cao nên thường xuyên lách được).
4. **Race Condition:** Cần phải đảm bảo ID của từng Job là duy nhất (`uuid4`) để không bị nhầm lẫn kết quả trả về trong hàng đợi.
