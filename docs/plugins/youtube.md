# Tài liệu: `proxify/plugins/youtube.py`

## 1. Tóm tắt tổng quan
File `youtube.py` định nghĩa plugin cho YouTube, với chức năng chính là chặn quảng cáo, tracker và thay đổi (inject) các đoạn script nhằm tự động bỏ qua các thông báo gián đoạn video trên nền tảng này.

## 2. Mục đích & Ý nghĩa
- Cải thiện trải nghiệm người dùng bằng cách loại bỏ quảng cáo.
- Tự động nhấn xác nhận "Có" khi YouTube hiện popup "Video đã bị tạm dừng. Tiếp tục xem?".
- Tối ưu hóa dung lượng mạng bằng cách ngắt (kill) sớm các request lấy quảng cáo.

## 3. Mối liên hệ
- Kế thừa `BasePlugin` và tự đăng ký tên `youtube`.
- Sử dụng các tiện ích `is_youtube_ad_request`, `strip_youtube_ads` từ `proxify.utils.youtube_utils` để thực hiện tác vụ phân tích URL và thay thế nội dung (content).
- Tương tác với cả request và response flow của mitmproxy.

## 4. Rủi ro (Risks & Edge Cases)
- **Hỏng chức năng UI YouTube:** Đoạn mã script tiêm vào (inject) sử dụng các query selector (`yt-confirm-dialog-renderer`). Nếu YouTube cập nhật giao diện và đổi class, script này sẽ vô dụng.
- **Lỗi định dạng response:** Việc cố gắng decode response body (`utf-8`) có thể gây ra ngoại lệ (mặc dù đã có try/except).
- **Phát hiện gian lận:** YouTube có cơ chế phát hiện trình chặn quảng cáo. Việc kill các request quảng cáo đôi lúc sẽ khiến player bị treo (loading mãi) hoặc bị cấm.

## 5. Chi tiết các Class và Hàm
### Class `YouTubePlugin(BasePlugin)`
Đảm nhiệm thao tác chặn QC và điều chỉnh nội dung YouTube.
- **Thuộc tính**:
  - `target_domains`: Chỉ áp dụng cho các host `youtube.com`, `googlevideo.com`, `youtubei`.
- **Hàm `on_request(self, flow: Any) -> None`**:
  - Lọc sớm theo domain.
  - Kiểm tra xem đường dẫn có phải là request quảng cáo không (thông qua `is_youtube_ad_request`).
  - Nếu là QC, ghi log, set cờ `ad_blocked` và gọi `flow.kill()` để chặn đứng ngay lập tức không gửi lên server.
- **Hàm `on_response(self, flow: Any) -> None`**:
  - Lọc sớm theo domain và kiểm tra xem có phải API hoặc trang watch (`youtube.com/watch`) không.
  - Lấy body response (decode UTF-8).
  - Chạy hàm `strip_youtube_ads(body)` để thanh lọc quảng cáo trong nội dung JSON/HTML trả về.
  - Nếu là trang `text/html` (chủ yếu là trang xem video), hàm sẽ chèn thêm một đoạn `<script>` JavaScript vào cuối thẻ `</body>`. Đoạn script này chạy vòng lặp setInterval (mỗi giây) để tìm kiếm các thông báo "tạm dừng" và mô phỏng thao tác click chuột vào nút "Có", sau đó ép chạy lại video.
  - Mã hoá ngược (encode) và gán lại cho `flow.response.content`.
