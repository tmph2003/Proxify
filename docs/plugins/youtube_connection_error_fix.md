# Tài Liệu Kỹ Thuật: Sửa Lỗi "Thi Thoảng Bị Lỗi Kết Nối" Trên YouTube (HTTP/2 Multiplexing & Heartbeat Fix)

## 1. Tóm tắt thay đổi
- **File sửa đổi 1:** `backend/proxify/plugins/youtube.py`
  - Thay thế lệnh hủy luồng mạng `flow.kill()` bằng phản hồi giả lập nhẹ nhàng: `http.Response.make(204, b"", ...)`.
  - Loại bỏ hoàn toàn việc tiêm mã JavaScript `<script>` vào HTML trang `/watch` do vi phạm nghiêm trọng chính sách bảo mật CSP (`require-trusted-types-for 'script'`) của YouTube.
- **File sửa đổi 2:** `backend/proxify/utils/youtube_utils.py`
  - Tinh chỉnh hàm `is_youtube_ad_request()`: không còn chặn oan request nhịp tim video chính `/api/stats/atr?ns=yt&el=detailpage`. Chỉ chặn khi tham số là `el=adunit` hoặc `adformat=`.
  - Loại bỏ logic kiểm tra substring `'ad_' in url_lower` quá rộng (dễ match nhầm các từ bình thường như `upload_date`, `download_url`, `thread_id`...). Thay bằng regex bắt chính xác tham số ad: `r'[?&]ad_(?:cpn|format|v)='`.
  - Bỏ script Anti-AFK nhúng vào HTML trong `strip_youtube_ads`.

## 2. Mục đích & Ý nghĩa
- **Triệu chứng lỗi:** Người dùng khi bật proxy lướt YouTube gặp hiện tượng: "Thi thoảng bị lỗi kết nối" (`net::ERR_HTTP2_PROTOCOL_ERROR`, `net::ERR_CONNECTION_CLOSED` hoặc video báo "Có lỗi xảy ra, vui lòng thử lại sau").
- **Nguyên nhân gốc rễ (Root Cause):**
  1. **HTTP/2 Multiplexing bị xé nát bởi `flow.kill()`:** Trong HTTP/2, nhiều stream (ảnh thumbnail, metadata, video chunks, heartbeat API) cùng chia sẻ một kết nối TCP duy nhất. Khi `flow.kill()` được gọi, Mitmproxy ngắt kết nối TCP và gửi cờ RST/Closed stream. Điều này làm cho các stream hợp lệ khác đang chạy song song trên cùng kết nối đó bị sập theo, ghi nhận lỗi log:
     ```text
     HTTP/2 protocol error: Invalid input ConnectionInputs.RECV_PING in state ConnectionState.CLOSED
     ```
  2. **Chặn oan Heartbeat của Video Player:** Endpoint `/api/stats/atr` với `el=detailpage` là token xác thực tiến trình phát video chính thức. Việc chặn và reset kết nối ở endpoint này khiến Web Player của YouTube coi như mạng bị đứt hoặc phát hiện bị can thiệp trái phép.
  3. **Vi phạm CSP TrustedTypes:** Việc chèn `<script>` thô vào HTML của trang `/watch` mà không có Nonce hợp lệ khiến trình duyệt Chromium chặn script và làm hỏng cơ chế Hydration của YouTube Single Page App (SPA).
- **Giải pháp kiến trúc:**
  - Chuyển cơ chế chặn quảng cáo từ **Network Termination (`flow.kill`)** sang **HTTP 204 No Content Response**. Trình duyệt nhận phản hồi rỗng thành công, quảng cáo và tracking bị triệt tiêu nhưng kết nối HTTP/2 TCP multiplexing hoàn toàn nguyên vẹn.
  - Tuân thủ nguyên tắc Single Responsibility: Proxy chỉ can thiệp tầng giao vận và lọc dữ liệu (Transport & Data Filtering), không can thiệp DOM injection vào HTML (nhiệm vụ này thuộc về Browser Extension / Content Script).

## 3. Mối liên hệ
- Liên quan trực tiếp tới:
  - `proxify/plugins/youtube.py`: YouTube Enhancer plugin.
  - `proxify/utils/youtube_utils.py`: Bộ nhận diện URL quảng cáo và xử lý chuỗi API.
  - `proxify/server.py`: Quản lý lifecycle của Mitmproxy và Router.

## 4. Rủi ro (Risks & Edge Cases)
- **Quảng cáo chèn trực tiếp vào Stream Video (Server-Side Ad Insertion):** Các đoạn video quảng cáo được stream trực tiếp từ `googlevideo.com` dưới dạng chunk video thuần sẽ không bị chặn ở tầng URL nếu chúng không chứa metadata đặc trưng. Việc này cần xử lý ở tầng Player API JSON `/youtubei/v1/player` (đã có hàm `strip_youtube_ads` hỗ trợ).
