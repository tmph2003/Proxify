# Gỡ bỏ cơ chế lấy Cookie từ Database

## 1. Tóm tắt thay đổi
- Đã xóa hoàn toàn hàm `get_cookies_and_ua_from_db` trong `proxify/platforms/facebook/token_store.py`.
- Gỡ bỏ lời gọi tới hàm này trong hàm `_resolve_cookie` của `proxify/platforms/facebook/crawler.py`.

## 2. Mục đích & Ý nghĩa
- **Bảo mật & Tránh checkpoint:** Việc dùng lại một cookie cũ (được lưu trong cơ sở dữ liệu từ lâu) có rủi ro cực cao bị Facebook khóa tài khoản (Checkpoint), do thông số trình duyệt (User-Agent) hoặc thời gian sống (Session) không còn khớp với thực tế. 
- Hệ thống crawler hiện tại đã được cấu trúc để dựa hoàn toàn vào cơ chế Template Fetching (cập nhật token nóng trong RAM) hoặc do người dùng trực tiếp cung cấp, đảm bảo token luôn "tươi" và khớp hoàn toàn về ngữ cảnh.

## 3. Mối liên hệ
- Ảnh hưởng trực tiếp tới `proxify/platforms/facebook/token_store.py` và `proxify/platforms/facebook/crawler.py`.
- Cơ chế fall-back cuối cùng khi không tìm thấy cookie trong Template giờ sẽ trực tiếp trả về rỗng, thay vì cố gắng truy vấn Database.

## 4. Rủi ro (Risks & Edge Cases)
- Rủi ro duy nhất là nếu người dùng không cung cấp Cookie từ UI và luồng tự động lấy Template cũng thất bại, Crawler sẽ lập tức dừng và báo lỗi "No cookies found!" thay vì chạy bằng cookie cũ. Điều này về cơ bản là một cải tiến bảo mật chứ không phải là lỗi.
