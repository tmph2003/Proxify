# Tài liệu: Sửa lỗi hiển thị trạng thái khi reload trang `facebook.html`

## Tóm tắt thay đổi
Đã thực hiện refactor mã JavaScript trong tệp `proxify/ui/templates/facebook.html`:
- Tách đoạn logic `setInterval` dùng để polling trạng thái (`/api/facebook/crawl_status`) từ bên trong hàm `startCrawl()` ra thành một hàm độc lập `pollGroupStatus()`.
- Bổ sung lệnh gọi hàm `pollGroupStatus()` vào bên trong hàm `checkRunningStatus()` khi phát hiện trạng thái đang chạy (running/fetching_template) khi tải lại trang (reload/re-enter).
- Xóa khai báo ẩn (inline) của logic interval cũ trong `startCrawl()`.

## Mục đích & Ý nghĩa
- **Vấn đề giải quyết:** Trước đây, khi người dùng khởi chạy tiến trình cào dữ liệu Facebook, giao diện sẽ bắt đầu polling để cập nhật trạng thái tiến trình (chạy vòng lặp để fetch status mỗi giây). Tuy nhiên, nếu người dùng thoát trang hoặc tải lại trang (`F5`), hàm `checkRunningStatus()` chỉ lấy trạng thái một lần duy nhất lúc load trang và hiển thị thông báo đó. Nó không thiết lập lại vòng lặp polling, dẫn đến việc thông báo bị "đứng hình" (ví dụ: kẹt ở "đang cào trang 5") và người dùng phải F5 thủ công để xem tiến độ mới.
- **Ý nghĩa:** Việc tách hàm `pollGroupStatus()` và tái sử dụng ở `checkRunningStatus()` đảm bảo rằng bất kể là người dùng vừa mới bấm nút Start hay là tải lại trang giữa chừng khi tiến trình đang chạy, giao diện vẫn sẽ tiếp tục polling và cập nhật tiến trình liên tục, thời gian thực cho người dùng.

## Mối liên hệ
- Tệp bị ảnh hưởng: `proxify/ui/templates/facebook.html`.
- Liên kết với API: Phụ thuộc vào endpoint `/api/facebook/crawl_status` được phục vụ từ `proxify/plugins/facebook.py`.
- Tác động: Cải thiện UX phần Frontend, không thay đổi logic Backend.

## Rủi ro (Risks & Edge Cases)
- **Hiệu năng:** Việc polling 1 giây/lần bằng hàm `setInterval` là chấp nhận được đối với ứng dụng cục bộ (localhost). Tuy nhiên, nếu có quá nhiều tab/trang cùng mở và cùng polling thì có thể gây ra một chút tải thừa cho backend.
- **Quản lý state:** Biến `groupStatusInterval` được khai báo là biến toàn cục (`let groupStatusInterval = null;`). Cần cẩn trọng khi clearInterval để tránh trường hợp memory leak hoặc nhiều interval chạy đè lên nhau nếu người dùng thao tác bấm nút Start nhiều lần (đã xử lý bằng lệnh `if (groupStatusInterval) clearInterval(groupStatusInterval);` trước khi gán mới).
