# Tài liệu: Hợp nhất nút Bắt đầu/Dừng lại thu thập

## Tóm tắt thay đổi
Đã chỉnh sửa giao diện HTML và JavaScript trong `proxify/ui/templates/facebook.html`:
- Xóa bỏ nút `stopCrawlBtn` (Dừng lại) bị dư thừa và có thiết kế chưa tối ưu.
- Sửa nút `crawlBtn` (Bắt đầu thu thập) thành một nút đa chức năng (toggle button).
- Bổ sung hàm `toggleCrawl()` để kiểm tra trạng thái toàn cục `window.isFeedCrawling`. Nếu đang chạy thì hiển thị hộp thoại xác nhận (confirm), nếu chọn Yes sẽ gọi hàm `stopCrawl()`. Nếu chưa chạy thì gọi `startCrawl()`.
- Cập nhật lại màu sắc và text của nút bằng cách chuyển đổi giữa 2 class CSS `.btn-crawl` (màu xanh dương mặc định) và `.btn-stop` (màu đỏ đối nghịch, có viền bo tròn) thay vì dùng inline style.

## Mục đích & Ý nghĩa
- **Vấn đề giải quyết:** Nút "Dừng lại" trước đây luôn hiển thị bên cạnh nút "Bắt đầu", chiếm không gian và làm giao diện trông rối mắt/xấu. Người dùng cảm thấy nó không cần thiết phải tách rời.
- **Ý nghĩa:** Tích hợp thành 1 nút duy nhất giúp giao diện gọn gàng hơn. Người dùng chỉ cần thao tác trên 1 nút, và có hộp thoại xác nhận khi Dừng (tránh việc bấm nhầm làm hỏng tiến trình đang cào dữ liệu).

## Mối liên hệ
- Tệp bị ảnh hưởng: `proxify/ui/templates/facebook.html`
- Các hàm bị thay đổi: `startCrawl()`, `stopCrawl()`, `pollGroupStatus()`, `checkRunningStatus()`.
- Biến toàn cục được tái sử dụng: `window.isFeedCrawling`

## Rủi ro (Risks & Edge Cases)
- **Trạng thái không đồng bộ:** Nếu vì lý do nào đó server bị lỗi và trả về trạng thái sai, nút có thể bị kẹt ở chữ "Dừng thu thập" hoặc "Bắt đầu thu thập". Điều này đã được giảm thiểu nhờ hàm `pollGroupStatus()` liên tục kiểm tra trạng thái thực tế từ backend mỗi giây và tự động reset giao diện về "Bắt đầu thu thập" khi tiến trình trên server chuyển sang `idle` hoặc `error`.
