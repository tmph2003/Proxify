# Cập nhật Luồng lấy thành viên & Giao diện Zalo

## Tóm tắt thay đổi
- Tích hợp theo dõi Job cho chức năng `Lấy toàn bộ thành viên`. Khi người dùng click, một Job sẽ được tạo và hiển thị trạng thái đang chạy trên UI.
- Hook JS của Zalo (trong `json_parse.js`) giờ đây sẽ phát đi một tín hiệu `fetchComplete` khi đã kéo xong toàn bộ user profile.
- API `extractor.py` bắt tín hiệu `fetchComplete` để tự động cập nhật trạng thái Job thành `completed` trong CSDL thông qua phương thức `mark_completed_by_group`.
- Trên UI, các Job sau khi hoàn thành sẽ **tự động biến mất khỏi danh sách** để không gây rối mắt, đồng thời hiển thị một **Toast thông báo nhỏ** góc phải dưới màn hình.
- Giao diện Zalo tự động lấy lại danh sách thành viên mỗi 3 giây nếu người dùng đang chọn 1 nhóm (auto-refresh).
- Bổ sung tính năng Sắp xếp (Sort) cho các cột trong bảng dữ liệu thành viên Zalo.
- Định dạng lại số điện thoại (chuyển `+84` thành `0`) và thêm thanh cuộn (scroll) cho bảng dữ liệu.

## Mục đích & Ý nghĩa
- Cung cấp phản hồi trực quan (visual feedback) bằng Toast khi xử lý lấy dữ liệu thành công.
- Ẩn bớt các Job đã chạy xong giúp danh sách Job bên Sidebar luôn gọn gàng, chỉ tập trung vào các Job đang kẹt hoặc đang chạy.
- Tự động hóa hoàn toàn quy trình hiển thị dữ liệu sau khi kéo xong, giúp luồng làm việc mượt mà hơn.
- Cải thiện UX với khả năng sắp xếp (Sort), giúp người dùng dễ tra cứu dữ liệu ngay trên giao diện mà không cần xuất file.

## Mối liên hệ
- File `backend/proxify/plugins/zalo.py`: Thêm logic tạo Job `fetch_members`.
- File `backend/proxify/platforms/zalo/js/json_parse.js`: Bổ sung payload `fetchComplete`.
- File `backend/proxify/platforms/zalo/extractor.py`: Bắt payload `fetchComplete` và update DB.
- UI `frontend/src/pages/Zalo.tsx` & `useZalo.ts`: Thêm sort, scroll, và auto-refresh dữ liệu.

## Rủi ro (Risks & Edge Cases)
- **Auto-Refresh liên tục:** Gọi API lấy members mỗi 3s nếu số lượng member cực lớn (ví dụ 10,000 người) có thể gây tải ngắn hạn. (Có thể khắc phục bằng cách chỉ refresh khi status của Job vừa đổi sang complete, thay vì setInterval gọi API liên tục - tạm thời cách làm hiện tại đáp ứng nhanh gọn).
- Tín hiệu `fetchComplete` có thể không được gửi đi nếu Zalo đổi API getGroupInfoV2. Tuy nhiên hệ thống vẫn kéo được dữ liệu từng phần.
