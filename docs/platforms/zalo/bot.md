# Tài liệu: `proxify/platforms/zalo/bot.py`

## 1. Tóm tắt tổng quan
File `bot.py` đóng vai trò là một tiến trình Worker quét tự động (Scan Worker) dành cho Zalo. Nó liên tục kiểm tra hàng đợi trong bảng `zalo.scan_jobs` để tìm các liên kết nhóm Zalo cần quét. Nếu có, nó sử dụng thư viện Playwright điều khiển trình duyệt Chromium chạy qua một MITM Proxy (Proxy đứng giữa). Thông qua các đoạn mã JS được tiêm ngầm bởi proxy, bot sẽ ép Zalo nạp toàn bộ thành viên trong nhóm và dữ liệu sẽ tự động được MITM Proxy lưu vào database.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Tự động hóa quá trình truy cập và lấy dữ liệu thành viên từ các nhóm Zalo mà không cần người dùng phải bấm bằng tay.
- **Ý nghĩa**: Bằng cách kết hợp Playwright thao tác UI và MITM Proxy để bắt gói tin JSON/GraphQL ngầm, hệ thống có thể thu thập thông tin khổng lồ một cách ổn định. Người dùng chỉ cần gửi một loạt đường link qua UI, bot sẽ chạy nền xử lý toàn bộ khối lượng công việc.

## 3. Mối liên hệ
- Nó kết nối cơ sở dữ liệu Zalo (`zalo_db`) để cập nhật trạng thái job (`jobs.update`).
- Trình duyệt Playwright được thiết lập chạy qua mạng cục bộ `PROXY_SERVER = "http://127.0.0.1:8080"` (MITM Proxy của Proxify). Khi bot mở trang Zalo, proxy này sẽ phụ trách tiêm hook (trong `zalo/extractor.py`).

## 4. Rủi ro (Risks & Edge Cases)
- **Tài khoản Zalo bị chặn/văng (Logout)**: Bot yêu cầu phải đăng nhập tài khoản Zalo Web. Nếu tài khoản Zalo bị phát hiện có hoạt động bất thường, nó có thể bị ép xuất ra, hoặc đòi giải Captcha liên tục. Hiện tại bot đã có code cảnh báo người dùng qua log nếu bị Captcha, nhưng vẫn yêu cầu sự can thiệp của con người.
- **Thay đổi giao diện Zalo**: Hàm `process_job` dựa vào việc tìm thẻ thẻ `a` hoặc text "Dùng bản Web" để lướt vào nhóm. Nếu Zalo đổi cấu trúc mã HTML landing page, bot có thể bị kẹt không vào được nhóm.
- **Javascript Hook thất bại**: Nếu Zalo đổi tên hàm nội bộ, lời gọi `window.__proxify_fetchFullGroupInfo` bằng `page.evaluate` sẽ thất bại.

## 5. Chi tiết các Class và Hàm

### 1. Hàm `async def ensure_logged_in(page)`
- **Mô tả**: Kiểm tra và đảm bảo Zalo Web đang ở trạng thái đã đăng nhập.
- **Cách hoạt động**: Truy cập `chat.zalo.me`. Dùng vòng lặp kiểm tra tiêu đề trang và bộ chọn class `.login-content`. Nếu chưa đăng nhập, sẽ yêu cầu người dùng lấy điện thoại quét mã QR và lặp lại kiểm tra mỗi 5s cho tới khi thành công.

### 2. Hàm `async def process_job(page, job, zalo_db)`
- **Mô tả**: Xử lý một tác vụ quét Zalo cụ thể từ hàng đợi.
- **Cách hoạt động**:
  - Đổi trạng thái job trong DB thành `running`.
  - Kiểm tra xem link có phải định dạng ép lấy id (`group_id:...`) không.
    - Nếu đúng định dạng `group_id:`, giữ trang tại `chat.zalo.me`, trực tiếp gọi hàm Hook JS tiêm từ proxy `window.__proxify_fetchFullGroupInfo` và chờ đợi 20s.
    - Nếu là link nhóm thông thường (`https://zalo.me/g/...`), mở link. Lưu HTML và ảnh chụp màn hình debug. 
    - Quét Captcha: Nếu thấy từ khóa Captcha, hiển thị cảnh báo yêu cầu người dùng tự bấm và đợi tối đa 60s.
    - Tự động bấm: Tìm link để mở "chat.zalo.me" hoặc tìm các nút có nội dung "Dùng bản Web", "Tham gia chat" để chui vào Zalo Web thay vì mở Zalo App.
    - Đợi 20s cho JS Hooks của Proxy bắt đầu thu thập thành viên nạp vào CSDL ngầm.
  - Sau khi vào nhóm, thực thi đoạn JS để trích xuất `group_id` từ URL hoặc bộ nhớ `window.__zalo_groupRuntime`.
  - Ép tải thành viên: Nếu thành công lấy `group_id`, gọi `window.__proxify_fetchFullGroupInfo(group_id)` để ép tải.
  - Sau 20s, nó sẽ dùng `zalo_db` query vào CSDL để đếm xem có bao nhiêu `members_found`.
  - Cập nhật lại job thành `completed` hoặc `error` nếu có lỗi văng ra.

### 3. Hàm `async def main()`
- **Mô tả**: Hàm vòng lặp chính của toàn bộ Worker Bot.
- **Cách hoạt động**: 
  - Khởi tạo Playwright Chromium, cấu hình proxy server trỏ về local.
  - Lưu hồ sơ (profile) của Zalo tại biến `USER_DATA_DIR` để giữ phiên đăng nhập không bị mất sau khi tắt.
  - Cấu hình bỏ qua cảnh báo chứng chỉ (`ignore_https_errors`) để tương thích MITM Proxy.
  - Bắt các log trên trình duyệt `page.on("console")` in ra terminal.
  - Đảm bảo đã đăng nhập `ensure_logged_in()`.
  - Chạy vòng lặp vô tận (infinite loop), gọi hàm `get_pending` từ DB. Nếu có job, chuyển cho `process_job`. Nếu không, sleep `POLL_INTERVAL` (3 giây) rồi lặp lại. Giới hạn xử lý khi trình duyệt lỡ bị tắt (bắt lỗi `TargetClosed`).
