# Sửa lỗi trạng thái Job Zalo bị kẹt

## Tóm tắt thay đổi
- Sửa lại script `json_parse.js` (được inject vào giao diện Zalo) để đảm bảo luôn bắn tín hiệu `fetchComplete` về Backend trong **mọi trường hợp**, kể cả khi nhóm không có thành viên nào hoặc API dự phòng (HTTP fallback) hoàn tất.

## Mục đích & Ý nghĩa
- Trước đây, nếu script Zalo gọi thành công hàm `getGroupInfoV2` và tìm thấy thành viên, nó mới bắn `fetchComplete`. Nhưng nếu script gọi API dự phòng (`fetchHiddenMembersHTTP`) hoặc nhóm trống, tín hiệu này bị bỏ quên. 
- Hậu quả là Backend không bao giờ nhận được báo cáo hoàn thành -> Trạng thái Job trong CSDL bị kẹt vĩnh viễn ở `running` -> UI hiển thị thông báo "Đang lấy dữ liệu..." vô tận (như screenshot bạn gặp phải).
- Thay đổi này đảm bảo Frontend luôn biết khi nào tiến trình Crawl kết thúc, từ đó UI sẽ tự động làm mới thành viên và ẩn Job đi mà không cần người dùng tải lại trang.

## Mối liên hệ
- File `backend/proxify/platforms/zalo/js/json_parse.js`: Nơi điều phối Crawl logic trên trình duyệt.
- `extractor.py`: Chờ nhận tín hiệu `fetchComplete` để cập nhật Database.

## Rủi ro (Risks & Edge Cases)
- Đã bao phủ các trường hợp exception chính. Không có rủi ro phụ vì đây chỉ là tín hiệu báo trạng thái luồng (control flow).
