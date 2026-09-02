# Cập nhật: Khôi phục logic hiển thị Trạng thái, Toast và Dừng thu thập trên giao diện Facebook

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/hooks/useFacebook.ts`: 
  - Khôi phục tính năng tự động gọi (polling) API `/facebook/crawl_status` mỗi giây (1s) để cập nhật trạng thái thu thập thời gian thực (status message).
  - Tự động dừng trạng thái "Đang thu thập" nếu API trả về trạng thái `idle` hoặc `error`.
  - Triển khai biến trạng thái cho màu sắc của hộp thông báo (`statusColor`) và hiển thị thông báo góc màn hình (`toastMessage`).
  - Đổi endpoint dừng crawl thành `/facebook/stop_crawl` (chuẩn xác hơn).
- Chỉnh sửa `frontend/src/pages/Facebook.tsx`:
  - Lấy các biến UI mới từ hook. Cập nhật giao diện `status-box` để hiển thị màu sắc đúng với trạng thái hệ thống.
  - Thêm thẻ `<div className="toast-container">` để khôi phục các thông báo nổi (Toast Notification) khi tải xong dữ liệu mới.
- Chỉnh sửa `backend/proxify/plugins/facebook.py`: 
  - Bổ sung đường dẫn (API Route) bị thiếu cho thao tác dừng Crawler: `POST /api/facebook/stop_crawl`.
  - Triển khai hàm `_handle_stop_crawl` gọi tín hiệu dừng thẳng tới lớp Crawler mặc định.

## Mục đích & Ý nghĩa
- Khắc phục lỗi giao diện bị kẹt ở trạng thái "Đang thu thập dữ liệu..." mà không hiển thị chi tiết tiến trình (vd: "Đang cuộn tìm...", "Đã cào được...").
- Cho phép người dùng dừng khẩn cấp quá trình thu thập thông qua nút "Dừng thu thập". Trước đó, tính năng này bị lỗi kết nối do backend không định nghĩa route tương ứng.
- Đem lại trải nghiệm thân thiện hơn với các thông báo nhỏ góc dưới (Toast) khi có bài viết hoặc bình luận mới được nạp vào kho.

## Mối liên hệ
- Liên quan mật thiết tới file hook điều phối logic chung của Facebook Crawler và giao diện trang Facebook ReactJS.

## Rủi ro (Risks & Edge Cases)
- Hàm dừng Crawler có thể không ngay lập tức giết được process nếu hệ thống đang kẹt ở thao tác fetch mạng, nhưng tín hiệu `stop_flag` đã được kích hoạt thành công.
