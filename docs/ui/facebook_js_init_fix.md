# Tài liệu: Sửa lỗi Javascript (ReferenceError) ngăn cản việc khởi tạo trang Facebook Extractor

## Tóm tắt thay đổi
Trong file `proxify/ui/templates/facebook.html`, hàm `loadState()` được gọi ngay khi định nghĩa để phục hồi trạng thái từ `localStorage`. Tuy nhiên, trong hàm này lại sử dụng các biến như `groupIdInput`, `startDateInput` và `endDateInput` (được định nghĩa bằng từ khóa `const` ở các dòng phía dưới). 
Thay đổi vừa được thực hiện là thay thế việc gọi trực tiếp các biến này bằng hàm `document.getElementById(...)` để tránh lỗi "can't access lexical declaration before initialization".

## Mục đích & Ý nghĩa
- **Giải quyết lỗi hiển thị ban đầu:** Trình duyệt thực thi Javascript theo nguyên tắc "Temporal Dead Zone" đối với `let` và `const`. Khi gọi `groupIdInput` trước khi nó được khởi tạo, một lỗi `ReferenceError` sẽ bị ném ra, làm cho luồng (thread) Javascript bị đứng (crash) ngay lập tức.
- **Phục hồi các chức năng phụ thuộc:** Do JS bị crash ở hàm `loadState()`, các đoạn code khởi tạo quan trọng phía sau (như `fetchResults()` để tải danh sách bài viết và ẩn màn hình "Chưa có dữ liệu") chưa bao giờ được chạy. Việc sửa lỗi này giúp trang web có thể gọi API và hiển thị toàn bộ thông tin bài viết ngay khi vừa mở trang.

## Mối liên hệ
- Chỉ ảnh hưởng trong phạm vi file `proxify/ui/templates/facebook.html`. Giúp quá trình khởi tạo trang (Initialization phase) diễn ra trơn tru.

## Rủi ro (Risks & Edge Cases)
- Đây là lỗi cú pháp/logic thực thi của Javascript nên việc sửa đổi này mang lại độ ổn định cao hơn, không gây rủi ro phá vỡ các chức năng khác. Việc dùng `document.getElementById` sẽ lấy trực tiếp Element từ cây DOM (vốn đã được render xong do script đặt ở cuối body), đảm bảo luôn lấy được đối tượng.
