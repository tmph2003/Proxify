# Tài liệu: youtube_utils.py

## 1. Tóm tắt tổng quan
Module tập hợp các hàm tiện ích xử lý đặc thù cho việc thao tác với lưu lượng mạng (traffic) của nền tảng YouTube, đặc biệt là loại bỏ quảng cáo và chống AFK.

## 2. Mục đích & Ý nghĩa
Giúp hệ thống chặn các script tải quảng cáo, tracking, đồng thời cung cấp giải pháp nhúng (inject) đoạn mã tự động click "Continue Watching" (Chống AFK) khi xem video quá lâu. Giúp tăng tính liên tục và giảm phiền nhiễu khi hệ thống đang giả lập trải nghiệm hoặc cào dữ liệu qua giao diện YouTube.

## 3. Mối liên hệ
Thường được nhúng vào các lớp chặn mạng (proxy script, mitm addons) trong Proxify. Khi các request/response đi qua Proxy, nội dung HTML hoặc JSON của YouTube sẽ được đưa qua module này để cắt tỉa (sanitize) trước khi trả về cho client.

## 4. Rủi ro (Risks & Edge Cases)
- **Tùy chỉnh Regex tĩnh (Brittle Logic):** Việc kiểm tra URL thông qua chuỗi cứng như `/api/stats/`, `el=adunit`, `ad_` mang tính cục bộ. Nếu YouTube thay đổi quy ước URL, tính năng chặn quảng cáo sẽ vô tác dụng.
- **Bẻ gãy luồng xử lý JSON của Frontend:** Hàm `strip_youtube_ads` dùng thao tác tìm và thay thế chuỗi text đơn giản (`replace`) thay vì parse JSON. Nếu có nội dung trong comment hoặc logic khác vô tình trùng tên (`adPlacements`), nội dung bị thay đổi có thể phá hỏng trang web.
- **Script Inject đơn giản:** Kỹ thuật chèn Anti-AFK Script thông qua việc thay thế chuỗi `</body>` sẽ thất bại nếu DOM trả về không chuẩn hoặc không có tag này (ví dụ response dạng chunk hoặc partial).

## 5. Chi tiết các Class và Hàm

- **Hàm `is_youtube_ad_request(url: str, domain: str) -> bool`**:
  - **Nhiệm vụ:** Đánh giá xem một HTTP request cụ thể có phải là luồng quảng cáo (ad) hoặc tracking hành vi của YouTube hay không.
  - **Logic:** Đầu tiên kiểm tra tên miền có phải họ `youtube` hoặc `googlevideo` hoặc URL có chứa `youtubei` không. Kế tiếp rà soát URL để bắt các mẫu (patterns) điển hình của quảng cáo như `/api/stats/` đi kèm `el=adunit`, hoặc các URL gửi tương tác như `/pcs/activeview`, `/pagead/interaction/`. Ngoài ra, cũng kiểm tra domain `doubleclick.net`. Trả về `True` nếu là quảng cáo, ngược lại là `False`.

- **Hàm `strip_youtube_ads(body: str) -> tuple[bool, str]`**:
  - **Nhiệm vụ:** Tiêm nhiễm/Sửa đổi nội dung gốc (body) của response trả về từ YouTube (có thể là HTML web ban đầu hoặc JSON API).
  - **Logic:**
    - Cắt bỏ (Block) các thành phần quảng cáo: Dùng cơ chế Replace String để đổi tên các khóa cấu hình JSON liên quan đến quảng cáo như `"adPlacements"`, `"playerAds"`, và `"adSlots"` thành biến thể bị block (`"_BLOCKED"`), làm vô hiệu hóa bộ máy render quảng cáo ở phía client browser.
    - Tiêm (Inject) Script Anti-AFK: Tìm tag `</body>` trong response body (nếu đó là HTML). Kế tiếp nhúng một đoạn JavaScript tự động chạy lặp lại (`setInterval` mỗi 5 giây). Đoạn script này tìm các thẻ popup cảnh báo (bằng tiếng Việt/Anh: "Video đã tạm dừng" / "Video paused") và sẽ tự động ấn nút Xác nhận (Confirm) để video tự động tiếp tục phát.
  - **Kết quả trả về:** Trả về một Tuple gồm `(modified: bool, new_body: str)`, báo hiệu cho interceptor biết body có sự thay đổi hay không để cập nhật lại biến content-length.
