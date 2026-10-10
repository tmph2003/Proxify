# Tài Liệu Kỹ Thuật: Cơ Chế Khóa Loại Trừ Tương Hỗ Khi Thu Thập Dữ Liệu (Mutually Exclusive Entity Crawling)

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/proxify/platforms/facebook/api.py`
  - `frontend/src/hooks/useFacebook.ts`
  - `frontend/src/pages/Facebook.tsx`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Khóa liên tác vụ (Mutual Exclusion) & Làm mờ trên Frontend (UI)**:
   - Khi tiến trình cào **Bài viết (Post / Feed crawl)** đang chạy:
     - Toàn bộ nút trong cột "Bình luận" ở bảng dữ liệu (gồm nút **"⬇️ Lấy bình luận"** và nút **"💬 x / y đã lấy"**) tự động chuyển sang trạng thái làm mờ, vô hiệu hóa:
       - `opacity: 0.35`
       - `filter: grayscale(80%)`
       - `cursor: not-allowed`
       - `disabled: true`
       - Tooltip rê chuột: *"⚠️ Đang cào bài viết (Post), tạm thời không thể thao tác bình luận"*
     - Nút "Bắt đầu cào bình luận ngay" trong modal bình luận bị vô hiệu hóa (`disabled`, `opacity: 0.5`, `cursor: not-allowed`).
     - Nút "🔄 Cập nhật / Cào tiếp" trong modal bình luận bị vô hiệu hóa kèm title giải thích.
     - Hiển thị banner cảnh báo màu vàng trong modal: *"⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Tính năng cào bình luận tạm thời bị khóa cho đến khi cào bài viết xong."*
     - Nút "💬 Cào BL" trong Floating Action Bar (cào bình luận hàng loạt) bị vô hiệu hóa.
   - Khi tiến trình cào **Bình luận (Comment crawl - đơn lẻ hoặc hàng loạt)** đang chạy:
     - Nút "Bắt đầu thu thập" bài viết ở bảng điều khiển bên trái bị vô hiệu hóa (`disabled`, `opacity: 0.5`, `cursor: not-allowed`), đổi nhãn thành *"⏳ Đang cào bình luận..."*.

2. **Bảo vệ chặt chẽ ở Backend API (Defensive API Layer)**:
   - Endpoint `/api/facebook/crawl` kiểm tra `is_any_comment_crawling()`: Nếu đang có tiến trình cào comment (đơn lẻ hoặc hàng loạt), từ chối request với mã lỗi 400 và thông báo rõ ràng.
   - Endpoint `/api/facebook/crawl_comments` và `/api/facebook/bulk_action` (với action `crawl_comments`) kiểm tra `is_post_crawling()`: Nếu đang có tiến trình cào feed bài viết, từ chối request với mã lỗi 400.
   - Endpoint `/api/facebook/crawl_status` trả về cờ trạng thái đồng bộ: `"is_comment_crawling"` và `"is_post_crawling"`.

---

## 2. Mục đích & Ý nghĩa

- **Mục đích:**
  - Đảm bảo an toàn tài khoản Facebook: Tránh việc người dùng hoặc hệ thống kích hoạt đồng thời nhiều luồng cào các thực thể khác nhau (Post, Comment, User) cùng lúc qua cùng một tài khoản / cookie.
  - Ngăn ngừa tình trạng nghẽn hàng đợi (Queue Congestion) và quá tải tài nguyên trên Chrome Extension Bridge.
  - Mang lại trải nghiệm người dùng trực quan, rõ ràng, ngăn ngừa xung đột thao tác nhầm lẫn.

---

## 3. Mối liên hệ kiến trúc

- **`FacebookCrawler` (`crawler.py`)**: Cung cấp hàm trạng thái `is_any_comment_crawling()` và `is_post_crawling()`.
- **`FacebookAPI` (`api.py`)**: Tầng bảo vệ Gateway API, chặn các thao tác xung đột trước khi đẩy vào worker.
- **`useFacebook` (`useFacebook.ts`)**: Hook quản trị trạng thái React, gom nhóm các trạng thái cào cục bộ và từ xa, cung cấp `isCommentCrawling` và `isPostCrawling` (`crawling`).
- **`FacebookPage` (`Facebook.tsx`)**: Tầng giao diện người dùng, phản ánh trạng thái disabled, tooltip và banner cảnh báo theo thời gian thực.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Người dùng mở modal bình luận khi đang cào bài viết:**
   - *Hành vi:* Người dùng vẫn có thể click mở modal để đọc các bình luận đã được lưu trước đó trong cơ sở dữ liệu.
   - *Kiểm soát:* Chỉ nút bấm gửi lệnh cào mới bị khóa (`disabled`). Việc đọc dữ liệu tĩnh (read-only) hoàn toàn không bị ảnh hưởng.
2. **Tiến trình cào gặp sự cố ngắt kết nối mạng hoặc treo:**
   - *Kiểm soát:* Cơ chế tự động reset trạng thái khi hoàn tất (`done`, `error`) hoặc hết timeout trên backend đảm bảo nút sẽ tự động mở khóa trở lại bình thường.
