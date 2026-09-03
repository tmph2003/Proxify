# Tài Liệu Kỹ Thuật: Cơ Chế Thử Lại (Retry) và Tăng Khả Năng Chịu Lỗi Của Extension Bridge

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/chrome_extension/background.js`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Khắc phục lỗi dừng đột ngột ở Crawler Backend (`crawler.py`)**:
   - Thêm cơ chế **Retry tự động** trong `_safe_request()`: Khi gửi job sang Extension, nếu request bị timeout hoặc gặp lỗi mạng tạm thời, hệ thống không dừng (abort) ngay lập tức mà sẽ thử lại (attempt 2) sau 2 giây nếu Extension vẫn đang duy trì heartbeat (`bridge.is_connected() == True`).
   - Tăng `bridge_timeout` từ **25s lên 40s** cho các trang feed sâu (trang 18, 19, 20...), nơi Facebook trả về payload GraphQL nặng từ 500KB - 1MB khiến máy chủ Meta phản hồi chậm hơn bình thường.
   - Chỉ khi cả 2 lần thử đều thất bại và Extension thực sự mất kết nối hoàn toàn thì hệ thống mới kích hoạt dừng khẩn cấp để bảo vệ tài khoản.

2. **Gia cố tính ổn định của Extension (`background.js`)**:
   - Thêm cờ khóa `isExecutingJob`: Ngăn chặn việc polling lấy job mới khi job hiện tại chưa chạy xong, triệt tiêu nguy cơ xung đột (race condition) nhiều request GraphQL cùng lúc trong một tab.
   - Lọc bỏ các tab bị Chrome Memory Saver đưa vào trạng thái ngủ đông (`!t.discarded`), đảm bảo `chrome.scripting.executeScript` luôn thực thi trên tab sống.
   - Bổ sung `AbortController` với timeout 35s cho lệnh `fetch()` trong tab, ngăn không cho tiến trình fetch bị treo vĩnh viễn nếu mạng Facebook bị đơ.

---

## 2. Mục đích & Ý nghĩa

- **Giải quyết triệt để vấn đề "đang crawl dở lại bị lỗi này"**:
  - Khi cào liên tục 19-20 trang (như trong log ghi nhận từ trang 1 đến trang 19 thành công liên tiếp), payload trả về từ Facebook tăng dần tới gần 1MB. Ở trang 20, máy chủ Meta mất 26s mới phản hồi.
  - Bộ đếm thời gian 25s cũ của Backend hết hạn trước khi nhận được dữ liệu, làm kích hoạt cơ chế Fail-safe nhầm, báo lỗi "Mất kết nối Chrome Extension" trong khi Extension vẫn đang chạy bình thường.
  - Bổ sung Timeout 40s + Retry giúp crawler vượt qua các đợt giật lag mạng tạm thời một cách êm ái mà không ngắt quãng công việc của người dùng.

---

## 3. Mối liên hệ kiến trúc

- **`FacebookCrawler._safe_request`**: Tầng điều phối yêu cầu mạng lai (Hybrid Network Coordinator).
- **`ExtensionBridge` (`bridge.py`)**: Tầng giao tiếp IPC bất đồng bộ giữa Docker Backend và Chrome Host.
- **`background.js`**: Tầng thực thi trong trình duyệt người dùng.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Mạng người dùng bị mất kết nối thực sự:**
   - *Kiểm soát:* Nếu rớt mạng thật, `bridge.is_connected()` sẽ quá ngưỡng 30s $\rightarrow$ Crawler sẽ không retry vô ích mà dừng an toàn.
2. **Tab Facebook bị đóng bởi người dùng trong khi đang cào:**
   - *Kiểm soát:* `background.js` tự động phát hiện và fallback sang các tab Facebook khác còn lại hoặc tạo tab Facebook nền mới.
